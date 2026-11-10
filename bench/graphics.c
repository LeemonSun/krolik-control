#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dxgi1_2.h>
#include <stdio.h>
#include <stdint.h>
static void string(const char *s){putchar('"');for(const unsigned char *p=(const unsigned char*)s;*p;p++){if(*p=='"'||*p=='\\')putchar('\\');if(*p>=32)putchar(*p);}putchar('"');}
int main(void){
 static const GUID iid={0x770aae78,0xf26f,0x4dba,{0xa8,0x29,0x25,0x3c,0x83,0xd1,0xb3,0x87}};
 IDXGIFactory1 *factory=NULL;if(FAILED(CreateDXGIFactory1(&iid,(void**)&factory)))return 1;
 int first=1;putchar('[');
 for(UINT i=0;i<16;i++){
  IDXGIAdapter1 *adapter=NULL;HRESULT h=IDXGIFactory1_EnumAdapters1(factory,i,&adapter);if(h==DXGI_ERROR_NOT_FOUND)break;if(FAILED(h))break;
  DXGI_ADAPTER_DESC1 d;
  if(SUCCEEDED(IDXGIAdapter1_GetDesc1(adapter,&d))&&!(d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)){
   char name[512]="";WideCharToMultiByte(CP_UTF8,0,d.Description,-1,name,sizeof(name),NULL,NULL);
   if(!first)putchar(',');first=0;
   printf("{\"name\":");string(name);printf(",\"key\":\"luid_0x%08lx_0x%08lx\",\"dedicated_bytes\":%llu,\"shared_limit_bytes\":%llu}",(unsigned long)(uint32_t)d.AdapterLuid.HighPart,(unsigned long)d.AdapterLuid.LowPart,(unsigned long long)d.DedicatedVideoMemory,(unsigned long long)d.SharedSystemMemory);
  }
  IDXGIAdapter1_Release(adapter);
 }
 putchar(']');IDXGIFactory1_Release(factory);return 0;
}
