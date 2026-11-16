"""Private directory creation and filesystem checks for the local contest seed."""
import csv
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from uuid import uuid4

SYSTEM = 'S-1-5-18'
ADMINISTRATORS = 'S-1-5-32-544'

# Path and SID travel as environment values. The script contains no interpolated code.
CHECK_WINDOWS_ACL = r"""
$ErrorActionPreference = 'Stop'
$path = $env:MGIMOV_CONTEST_ACL_PATH
$directory = $env:MGIMOV_CONTEST_ACL_DIRECTORY -eq '1'
$sidType = [System.Security.Principal.SecurityIdentifier]
$expected = @($env:MGIMOV_CONTEST_ACL_USER, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique
$attributes = [IO.File]::GetAttributes($path)
if (($attributes -band [IO.FileAttributes]::ReparsePoint) -or
    [bool]($attributes -band [IO.FileAttributes]::Directory) -ne $directory) {
    throw 'Unexpected object type or reparse point.'
}
$acl = if ($directory) { [IO.Directory]::GetAccessControl($path) } else { [IO.File]::GetAccessControl($path) }
if ($acl.GetOwner($sidType).Value -notin $expected -or ($directory -and -not $acl.AreAccessRulesProtected)) {
    throw 'Unexpected owner or directory inheritance.'
}
$rules = @($acl.GetAccessRules($true, $true, $sidType))
$seen = @()
foreach ($rule in $rules) {
    if ($rule.IdentityReference.Value -notin $expected -or
        $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl' -or
        $rule.PropagationFlags -ne 'None' -or
        ($directory -and ($rule.IsInherited -or [int]$rule.InheritanceFlags -ne 3)) -or
        (-not $directory -and $rule.InheritanceFlags -ne 'None')) {
        throw 'Unexpected ACL entry.'
    }
    $seen += $rule.IdentityReference.Value
}
if (@($expected | Where-Object { $_ -notin $seen }).Count -ne 0) {
    throw 'Required ACL entry missing.'
}
"""

CHECK_WINDOWS_CHAIN = r"""
$ErrorActionPreference = 'Stop'
$path = $env:MGIMOV_CONTEST_ACL_PATH
# The Windows servicing principal can own the volume root.
$trusted = @($env:MGIMOV_CONTEST_ACL_USER, 'S-1-5-18', 'S-1-5-32-544',
             'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$volume = [IO.Path]::GetPathRoot($path)
if ($volume -notmatch '^[A-Za-z]:\\$' -or [IO.DriveInfo]::new($volume).DriveType -ne 'Fixed') {
    throw 'Only a local fixed Windows volume is supported.'
}
$paths = @()
for ($at = [IO.DirectoryInfo]::new($path); $null -ne $at; $at = $at.Parent) {
    $paths = @($at.FullName) + $paths
}
foreach ($node in $paths) {
    $attributes = [IO.File]::GetAttributes($node)
    if (-not ($attributes -band [IO.FileAttributes]::Directory) -or
        ($attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Reparse point or non-directory in path: $node"
    }
    $acl = [IO.Directory]::GetAccessControl($node)
    $raw = [System.Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
    if ($null -eq $raw.DiscretionaryAcl -or $raw.Owner.Value -notin $trusted) {
        throw "Untrusted owner or unrestricted DACL: $node"
    }
    # DELETE, DELETE_CHILD, WRITE_DAC, WRITE_OWNER, write-data/EA/attributes and generic write/all.
    $dangerous = 0x500D0152
    # At the volume root only, adding a sibling directory cannot change an existing path.
    if ($node -ne $volume) { $dangerous = $dangerous -bor 4 }
    foreach ($ace in $raw.DiscretionaryAcl) {
        if ([int]$ace.AceFlags -band 8) { continue } # INHERIT_ONLY_ACE
        if ($ace -isnot [System.Security.AccessControl.CommonAce] -or
            $ace.AceType -notin @('AccessAllowed', 'AccessDenied')) {
            throw "Unsupported DACL entry: $node"
        }
        if ($ace.AceType -eq 'AccessAllowed' -and $ace.SecurityIdentifier.Value -notin $trusted -and
            ($ace.AccessMask -band $dangerous)) {
            throw "Unsafe ACL permits a non-trusted SID to modify or delete a path component: $node"
        }
    }
}
"""


def windows_user_sid():
    executable = Path(os.environ['SystemRoot']) / 'System32' / 'whoami.exe'
    result = subprocess.run([executable, '/user', '/fo', 'csv', '/nh'],
                            capture_output=True, check=True, timeout=15)
    # The SID is ASCII even when Windows encodes the account name in the console code page.
    rows = list(csv.reader(result.stdout.decode('ascii', errors='replace').splitlines()))
    if len(rows) != 1 or len(rows[0]) != 2 or not re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+)+', rows[0][1]):
        raise PermissionError('Could not identify the current Windows user SID.')
    return rows[0][1]


def create_windows_directory(path, user_sid):
    """Create the directory with a protected DACL in the same Windows API call."""
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('descriptor', wintypes.LPVOID),
                    ('inherit_handle', wintypes.BOOL)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), wintypes.LPVOID]
    convert.restype = wintypes.BOOL
    create = kernel.CreateDirectoryW
    create.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    create.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID

    trustees = dict.fromkeys((user_sid, SYSTEM, ADMINISTRATORS))
    sddl = f'O:{user_sid}D:P' + ''.join(f'(A;OICI;FA;;;{sid})' for sid in trustees)
    descriptor = wintypes.LPVOID()
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        if not create(str(path), ctypes.byref(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def run_windows_check(path, user_sid, script, **values):
    powershell = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    env = dict(os.environ, MGIMOV_CONTEST_ACL_PATH=str(path), MGIMOV_CONTEST_ACL_USER=user_sid, **values)
    try:
        subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                       env=env, capture_output=True, check=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        raise PermissionError(f'Windows path or ACL is not trusted: {path}') from error


def check_windows_chain(path, user_sid):
    run_windows_check(path, user_sid, CHECK_WINDOWS_CHAIN)


def check_windows_acl(path, user_sid, *, directory):
    run_windows_check(path, user_sid, CHECK_WINDOWS_ACL,
                      MGIMOV_CONTEST_ACL_DIRECTORY=str(int(directory)))


class PrivateDemoDirectory:
    def __init__(self, parent):
        if os.name == 'nt':
            self.user_sid = windows_user_sid()
            check_windows_chain(parent, self.user_sid)
            self.path = parent / ('contest-demo-' + uuid4().hex)
            create_windows_directory(self.path, self.user_sid)
        elif os.name == 'posix':
            self.path = Path(tempfile.mkdtemp(prefix='contest-demo-', dir=parent))
        else:
            raise PermissionError('Unsupported filesystem permissions for the demo.')

    def check_directory(self):
        if os.name == 'nt':
            check_windows_acl(self.path, self.user_sid, directory=True)
        else:
            info = self.path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError('Demo directory must be owned by the current user and have mode 0700.')

    def check_database(self, database):
        self.check_directory()
        for suffix in ('', '-journal', '-wal', '-shm'):
            path = database.with_name(database.name + suffix)
            if suffix and not os.path.lexists(path):
                continue
            if os.name == 'nt':
                check_windows_acl(path, self.user_sid, directory=False)
            else:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                    raise PermissionError(f'Unexpected demo database file: {path}')
                path.chmod(0o600)
                if stat.S_IMODE(path.stat().st_mode) != 0o600:
                    raise PermissionError(f'Demo database file must have mode 0600: {path}')
