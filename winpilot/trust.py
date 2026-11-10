"""Authenticode verification using the documented WinVerifyTrust policy."""
import ctypes as C
class GUID(C.Structure):_fields_=[('data1',C.c_uint32),('data2',C.c_uint16),('data3',C.c_uint16),('data4',C.c_ubyte*8)]
class FILE(C.Structure):_fields_=[('size',C.c_uint32),('path',C.c_wchar_p),('file',C.c_void_p),('subject',C.c_void_p)]
class DATA(C.Structure):_fields_=[('size',C.c_uint32),('callback',C.c_void_p),('sip',C.c_void_p),('ui',C.c_uint32),('revoke',C.c_uint32),('choice',C.c_uint32),('file',C.POINTER(FILE)),('action',C.c_uint32),('state',C.c_void_p),('url',C.c_wchar_p),('flags',C.c_uint32),('context',C.c_uint32),('settings',C.c_void_p)]
def verify(path):
 w=C.WinDLL('wintrust',use_last_error=True);w.WinVerifyTrust.argtypes=[C.c_void_p,C.POINTER(GUID),C.POINTER(DATA)];w.WinVerifyTrust.restype=C.c_int32
 action=GUID(0xaac56b,0xcd44,0x11d0,(C.c_ubyte*8)(0x8c,0xc2,0,0xc0,0x4f,0xc2,0x95,0xee));f=FILE();f.size=C.sizeof(f);f.path=str(path);data=DATA();data.size=C.sizeof(data);data.ui=2;data.choice=1;data.file=C.pointer(f);data.action=1;data.flags=0x1000
 try:
  status=w.WinVerifyTrust(C.c_void_p(-1),C.byref(action),C.byref(data))
  if status!=0:raise ValueError('Подпись модуля не подтверждена Windows: '+f'0x{status&0xffffffff:08X}')
 finally:data.action=2;w.WinVerifyTrust(C.c_void_p(-1),C.byref(action),C.byref(data))
