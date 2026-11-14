"""Export the current source, including untracked MVP modules, without private state."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from ..config import ROOT

SOURCE_SUFFIXES = {
    'backend': {'.py', '.sql'},
    'frontend': {'.html', '.css', '.js'},
    'tests': {'.py', '.js', '.mjs'},
}
REQUIRED_FILES = {
    'requirements.txt', 'requirements-test.txt', 'constraints.txt', 'package.json',
    'README.md', 'RELEASE.md', '.gitignore', '.gitattributes',
    'tests/browser/package.json', 'tests/browser/package-lock.json', 'tests/browser/README.md',
}


def release_files():
    listed = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT,
    )
    # Check tracked paths too: Git still lists a tracked file after it is ignored.
    ignored = subprocess.run(
        ['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=ROOT,
        input=listed, stdout=subprocess.PIPE, check=False,
    )
    if ignored.returncode not in (0, 1):
        ignored.check_returncode()
    ignored_paths = set(ignored.stdout.decode('utf-8').split('\0'))
    selected = set()
    for name in listed.decode('utf-8').split('\0'):
        if name in ignored_paths:
            continue
        relative = Path(name)
        path = ROOT / relative
        if name not in REQUIRED_FILES and (
            len(relative.parts) < 2 or relative.suffix not in SOURCE_SUFFIXES.get(relative.parts[0], ())
        ):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or not path.is_file():
            continue
        selected.add(name)
    missing = REQUIRED_FILES - selected
    if missing:
        raise ValueError('Release source is incomplete: ' + ', '.join(sorted(missing)))
    return [ROOT / name for name in sorted(selected)]

def export(destination):
    target=(ROOT/Path(destination)).resolve();allowed=(ROOT/'.tmp/releases').resolve()
    archive=target.with_suffix('.zip')
    if not target.is_relative_to(allowed) or target==allowed:raise ValueError('Use a new directory under .tmp/releases/')
    if target.exists() or archive.exists() or archive.with_suffix('.zip.sha256').exists():raise ValueError('Existing release is never overwritten')
    files=release_files()
    if any(not path.is_file() for path in files):raise ValueError('Release source is incomplete')
    # No .git, environments, databases, credentials, logs, user data or entire docs tree.
    manifest={'format':1,'base_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'source':'working tree including untracked files; not a Git commit','files':{}}
    target.mkdir(parents=True)
    for path in files:
        relative=path.relative_to(ROOT).as_posix();data=path.read_bytes()
        output=target/relative;output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data)
        manifest['files'][relative]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    data=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
    (target/'RELEASE-MANIFEST.json').write_bytes(data)
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
        for relative in sorted([*manifest['files'],'RELEASE-MANIFEST.json']):
            info=zipfile.ZipInfo(relative,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            output.writestr(info,(target/relative).read_bytes())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    return target,archive,digest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    target,archive,digest=export(args.output)
    print('Exported',len(release_files()),'source files; no private database or credentials.')
    print(archive.relative_to(ROOT).as_posix(),digest)
if __name__=='__main__':main()
