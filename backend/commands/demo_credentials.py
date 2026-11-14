"""Current-Windows-user DPAPI delivery. No plaintext files or command-line passwords."""
import argparse,ctypes,json,os,sys
from pathlib import Path
from ..config import ROOT

class Blob(ctypes.Structure):
    _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protect(data,decrypt=False):
    if os.name!='nt':raise ValueError('DPAPI requires Windows; use interactive seed instead.')
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):raise OSError('DPAPI failed')
    try:return ctypes.string_at(target.data,target.size)
    finally:ctypes.windll.kernel32.LocalFree(target.data)

def path_for(value):
    path=(ROOT/Path(value)).resolve()
    if not path.is_relative_to((ROOT/'.tmp').resolve()) or path.suffix!='.dpapi':raise ValueError('Use .tmp/*.dpapi inside project.')
    return path

def save(value,credentials):
    path=path_for(value);encrypted=protect(json.dumps(credentials).encode())
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as output:output.write(encrypted)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--file',required=True);args=parser.parse_args()
    if not sys.stdout.isatty():raise SystemExit('Credentials can only be viewed in a private interactive terminal.')
    data=json.loads(protect(path_for(args.file).read_bytes(),True))
    for login,password in data.items():print(login+': '+password)
if __name__=='__main__':main()
