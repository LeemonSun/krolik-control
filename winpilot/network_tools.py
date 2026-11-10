"""Network measurements with explicit scope and bounded numeric interpretation."""
import ipaddress
import math
import socket
import ssl
import time

def latency(raw):
 samples=raw.get('samples',[]) if isinstance(raw,dict) else []
 if isinstance(samples,dict):samples=[samples]
 valid=[r for r in samples[:8] if isinstance(r,dict) and type(r.get('ok'))==bool]
 values=[float(r['milliseconds']) for r in valid if r['ok'] and type(r.get('milliseconds')) in (int,float) and math.isfinite(r['milliseconds']) and 0<=r['milliseconds']<=700]
 sent=len(valid);lost=sent-len(values)
 return {'sent':sent,'received':len(values),'loss_percent':round(lost/sent*100,1) if sent else None,'min_ms':min(values) if values else None,'mean_ms':round(sum(values)/len(values),2) if values else None,'max_ms':max(values) if values else None,'jitter_ms':round(sum(abs(b-a) for a,b in zip(values,values[1:]))/(len(values)-1),2) if len(values)>1 else None,'samples':valid,'note':'8 ICMP-запросов к выбранному узлу. ICMP могут блокировать; отсутствие ответа не доказывает отсутствие интернета. Джиттер — средняя разница между соседними полученными ответами.'}

def connect(host,addresses,stop,stage):
 from .files import check
 stages=[];sock=None;last='Адрес не найден'
 unique=[]
 for value in addresses[:8]:
  try:address=str(ipaddress.ip_address(value))
  except (ValueError,TypeError):continue
  if address not in unique:unique.append(address)
 for address in unique[:3]:
  check(stop);stage('TCP · '+address);started=time.perf_counter()
  candidate=socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET,socket.SOCK_STREAM);candidate.settimeout(3)
  try:candidate.connect((address,443));sock=candidate;stages.append({'name':'TCP · 443','status':'passed','milliseconds':round((time.perf_counter()-started)*1000,1),'detail':address});break
  except OSError as e:last=str(e)[:300];candidate.close()
 if not sock:return [{'name':'TCP · 443','status':'failed' if unique else 'unavailable','detail':last}]
 try:
  check(stop);stage('TLS · проверка сертификата');started=time.perf_counter();sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host);stages.append({'name':'TLS','status':'passed','milliseconds':round((time.perf_counter()-started)*1000,1),'detail':'Сертификат проверен для '+host})
 except (OSError,ssl.SSLError) as e:stages.append({'name':'TLS','status':'failed','detail':str(e)[:500]})
 finally:sock.close()
 return stages
