"""Short selected-endpoint WASAPI test and peak meter. No recordings are saved."""
import ctypes as C
import math
import struct
import time
from contextlib import contextmanager
from .audio import guid,GUID,DWORD,call,check,release,enumerator

IID_CLIENT=guid('1CB9AD4C-DBFA-4C32-B178-C2F568A703B2')
IID_RENDER=guid('F294ACFC-3146-4483-A7BF-ADDCA7C260E2')
IID_CAPTURE=guid('C8ADBD64-E71E-48A0-A4DE-185C395CD317')
IID_METER=guid('C02216F6-8C67-4B5B-9D00-D008E73E0064')

@contextmanager
def activated(device,iid):
    pointer=C.c_void_p()
    check(call(device,3,[C.POINTER(GUID),DWORD,C.c_void_p,C.POINTER(C.c_void_p)],C.byref(iid),23,None,C.byref(pointer)))
    try:yield pointer
    finally:release(pointer)

@contextmanager
def endpoint(ident):
    with enumerator() as (enum,ole):
        device=C.c_void_p()
        check(call(enum,5,[C.c_wchar_p,C.POINTER(C.c_void_p)],ident,C.byref(device)))
        try:yield device,ole
        finally:release(device)

@contextmanager
def audio_stream(device,ole):
    with activated(device,IID_CLIENT) as client:
        fmt=C.c_void_p()
        try:
            check(call(client,8,[C.POINTER(C.c_void_p)],C.byref(fmt)))
            raw=C.string_at(fmt,18);tag,channels,rate,avg,align,bits,extra=struct.unpack('<HHIIHHH',raw)
            if not 1<=channels<=32 or not 8000<=rate<=384000 or align!=channels*((bits+7)//8):raise ValueError('Необычный формат устройства; тест недоступен')
            subtype=struct.unpack('<I',C.string_at(fmt.value+24,4))[0] if tag==0xfffe and extra>=22 else tag
            check(call(client,3,[C.c_int,DWORD,C.c_int64,C.c_int64,C.c_void_p,C.c_void_p],0,0,5000000,0,fmt,None))
            yield client,{'channels':channels,'rate':rate,'align':align,'bits':bits,'subtype':subtype}
        finally:
            # Stop also works on a client that was never started.
            call(client,11,[])
            if fmt:ole.CoTaskMemFree(fmt)


def tone_samples(frames,channels,rate,bits,subtype,channel=None):
    if (subtype,bits) not in [(3,32),(1,16),(1,24),(1,32)]:raise ValueError('Формат тестового сигнала не поддерживается')
    if channel is not None and (type(channel)!=int or not 0<=channel<channels):raise ValueError('Выбранный канал отсутствует у устройства')
    data=bytearray()
    for n in range(frames):
        envelope=min(1,n/(rate*.012),(frames-1-n)/(rate*.012))
        value=math.sin(2*math.pi*660*n/rate)*.06*max(0,envelope)
        if subtype==3:sample=struct.pack('<f',value)
        else:sample=int(value*((1<<(bits-1))-1)).to_bytes(bits//8,'little',signed=True)
        data.extend(sample*channels if channel is None else b''.join(sample if i==channel else bytes(len(sample)) for i in range(channels)))
    return bytes(data)


def test_output(ident,channel=None):
    with endpoint(ident) as (device,ole),audio_stream(device,ole) as (client,fmt):
        size=DWORD();check(call(client,4,[C.POINTER(DWORD)],C.byref(size)))
        frames=min(size.value,int(fmt['rate']*.35))
        if frames<1:raise ValueError('Аудиобуфер недоступен')
        data=tone_samples(frames,fmt['channels'],fmt['rate'],fmt['bits'],fmt['subtype'],channel)
        renderer=C.c_void_p()
        check(call(client,14,[C.POINTER(GUID),C.POINTER(C.c_void_p)],C.byref(IID_RENDER),C.byref(renderer)))
        try:
            pointer=C.c_void_p();check(call(renderer,3,[DWORD,C.POINTER(C.c_void_p)],frames,C.byref(pointer)))
            C.memmove(pointer,data,len(data));check(call(renderer,4,[DWORD,DWORD],frames,0))
            check(call(client,10,[]));time.sleep(frames/fmt['rate']+.05)
        finally:release(renderer)
    return {'message':'Проверка завершена. Если сигнала не было слышно, проверьте громкость выбранного устройства.'}


def meter_input(ident,callback):
    with endpoint(ident) as (device,ole),activated(device,IID_METER) as meter,audio_stream(device,ole) as (client,fmt):
        check(call(client,10,[]))
        capture=C.c_void_p();check(call(client,14,[C.POINTER(GUID),C.POINTER(C.c_void_p)],C.byref(IID_CAPTURE),C.byref(capture)))
        highest=0
        try:
            for i in range(80):
                value=C.c_float();check(call(meter,3,[C.POINTER(C.c_float)],C.byref(value)))
                peak=max(0,min(1,value.value));highest=max(highest,peak)
                callback({'id':ident,'peak':peak,'maximum':highest,'running':True,'seconds':round((80-i)/10,1)})
                time.sleep(.1)
                packet=DWORD()
                check(call(capture,5,[C.POINTER(DWORD)],C.byref(packet)))
                while packet.value:
                    pointer=C.c_void_p();frames=DWORD();flags=DWORD()
                    check(call(capture,3,[C.POINTER(C.c_void_p),C.POINTER(DWORD),C.POINTER(DWORD),C.c_void_p,C.c_void_p],C.byref(pointer),C.byref(frames),C.byref(flags),None,None))
                    check(call(capture,4,[DWORD],frames.value))
                    check(call(capture,5,[C.POINTER(DWORD)],C.byref(packet)))
        finally:release(capture)
    result={'id':ident,'peak':0,'maximum':highest,'running':False,'seconds':0,'message':'Проверка закончена; звук не записывался'};callback(result);return result


def pcm_values(data,fmt):
    if fmt['subtype']==3 and fmt['bits']==32:return [max(-1.,min(1.,v[0])) if math.isfinite(v[0]) else 0. for v in struct.iter_unpack('<f',data)]
    if fmt['subtype']==1 and fmt['bits'] in (16,24,32):
        size=fmt['bits']//8;scale=float(1<<(fmt['bits']-1));return [int.from_bytes(data[i:i+size],'little',signed=True)/scale for i in range(0,len(data),size)]
    raise ValueError('Формат записи не поддерживается')


def record_voice(ident,cancel,progress):
    chunks=[];size=0
    with endpoint(ident) as (device,ole),audio_stream(device,ole) as (client,fmt):
        if (fmt['subtype'],fmt['bits']) not in ((3,32),(1,16),(1,24),(1,32)):raise ValueError('Формат микрофона не поддерживается')
        capture=C.c_void_p();check(call(client,14,[C.POINTER(GUID),C.POINTER(C.c_void_p)],C.byref(IID_CAPTURE),C.byref(capture)))
        try:
            check(call(client,10,[]));start=time.monotonic();pause=False
            while time.monotonic()-start<6:
                if cancel.is_set():
                    from .care import Cancelled
                    raise Cancelled()
                if not pause and time.monotonic()-start>=5:progress('Теперь помолчите одну секунду');pause=True
                packet=DWORD();check(call(capture,5,[C.POINTER(DWORD)],C.byref(packet)))
                while packet.value:
                    pointer=C.c_void_p();frames=DWORD();flags=DWORD()
                    check(call(capture,3,[C.POINTER(C.c_void_p),C.POINTER(DWORD),C.POINTER(DWORD),C.c_void_p,C.c_void_p],C.byref(pointer),C.byref(frames),C.byref(flags),None,None))
                    try:
                        count=frames.value*fmt['align'];size+=count
                        if size>16*1024*1024:raise ValueError('Формат записи требует слишком большой буфер')
                        chunks.append(bytes(count) if flags.value&2 else C.string_at(pointer,count))
                    finally:check(call(capture,4,[DWORD],frames.value))
                    check(call(capture,5,[C.POINTER(DWORD)],C.byref(packet)))
                time.sleep(.01)
        finally:release(capture)
    return {'data':b''.join(chunks),'format':fmt}


def voice_metrics(recording):
    fmt=recording['format'];values=pcm_values(recording['data'],fmt)
    if not values:raise ValueError('Микрофон не передал аудиоданные')
    peak=max(abs(v) for v in values);rms=math.sqrt(sum(v*v for v in values)/len(values));pause=values[-fmt['rate']*fmt['channels']:]
    db=lambda v:round(20*math.log10(max(v,1e-6)),1)
    return {'peak_dbfs':db(peak),'rms_dbfs':db(rms),'pause_rms_dbfs':db(math.sqrt(sum(v*v for v in pause)/len(pause))),'clipping_percent':round(sum(abs(v)>=.999 for v in values)*100/len(values),2),'duration_s':round(len(values)/fmt['channels']/fmt['rate'],2)}


def play_voice(recording):
    import io,wave,winsound
    fmt=recording['format'];values=pcm_values(recording['data'],fmt);channels=fmt['channels'];frames=len(values)//channels
    mono=[sum(values[i*channels:(i+1)*channels])/channels for i in range(frames)];pcm=b''.join(struct.pack('<h',round(max(-1,min(1,v))*32767)) for v in mono);memory=io.BytesIO()
    with wave.open(memory,'wb') as file:file.setnchannels(1);file.setsampwidth(2);file.setframerate(fmt['rate']);file.writeframes(pcm)
    winsound.PlaySound(memory.getvalue(),winsound.SND_MEMORY)
    return {'message':'Запись воспроизведена на основном выходе Windows'}
