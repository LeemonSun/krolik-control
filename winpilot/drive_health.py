"""Read NVMe SMART via the documented STORAGE_PROTOCOL_SPECIFIC_DATA query."""
import ctypes as C
import json
import os
import struct
import sys

def parse(log):
    if len(log)<512:raise ValueError('Неполный NVMe SMART')
    kelvin=int.from_bytes(log[1:3],'little');temp=round(kelvin-273.15,1) if kelvin not in (0,65535) and -30<=kelvin-273.15<=150 else None
    return {'warning_bits':log[0],'temperature_c':temp,'available_spare_percent':log[3] if log[3]<=100 else None,'spare_threshold_percent':log[4] if log[4]<=100 else None,'percentage_used':log[5],**{name:str(int.from_bytes(log[offset:offset+16],'little')) for name,offset in [('power_cycles',112),('power_on_hours',128),('unsafe_shutdowns',144),('media_errors',160),('error_log_entries',176)]}}
def query(number):
    if type(number)!=int or not 0<=number<=255:raise ValueError('Неверный номер накопителя')
    if os.name!='nt':raise ValueError('Доступно в Windows')
    k=C.WinDLL('kernel32',use_last_error=True);k.CreateFileW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint32,C.c_void_p];k.CreateFileW.restype=C.c_void_p;k.DeviceIoControl.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.POINTER(C.c_uint32),C.c_void_p];k.CloseHandle.argtypes=[C.c_void_p]
    h=k.CreateFileW('\\\\.\\PhysicalDrive'+str(number),0,3,None,3,0,None)
    if h==C.c_void_p(-1).value:raise OSError(C.get_last_error(),'Нет доступа к накопителю')
    try:
        data=struct.pack('<12I',50,0,3,2,2,0,40,512,0,0,0,0)+bytes(512);buffer=C.create_string_buffer(data,len(data));returned=C.c_uint32()
        if not k.DeviceIoControl(h,0x2d1400,buffer,len(data),buffer,len(data),C.byref(returned),None):raise OSError(C.get_last_error(),'NVMe SMART недоступен через этот контроллер')
        raw=buffer.raw
        if returned.value<48:raise ValueError('Неполный ответ накопителя')
        version,size=struct.unpack_from('<2I',raw)
        if version<48 or size<48 or size>returned.value:raise ValueError('Неверный дескриптор NVMe')
        protocol,kind,request,sub,offset,length=struct.unpack_from('<6I',raw,8)
        if protocol!=3 or kind!=2 or offset<40 or length<512 or 8+offset+length>returned.value:raise ValueError('Неверные границы NVMe ответа')
        return parse(raw[8+offset:8+offset+512])
    finally:k.CloseHandle(h)
if __name__=='__main__':
    try:print(json.dumps({'available':True,**query(int(sys.argv[1]))}))
    except Exception as e:print(json.dumps({'available':False,'reason':str(e)}))
