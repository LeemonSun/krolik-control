/* Read-only driver metrics. ADL type definitions are MIT-licensed; see data/ADL-LICENSE.txt. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wintrust.h>
#include <softpub.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../vendor/adl/include/adl_sdk.h"
typedef int (__cdecl *CREATE)(ADL_MAIN_MALLOC_CALLBACK,int,void**);
typedef int (__cdecl *DESTROY)(void*);
typedef int (__cdecl *NUMBER)(void*,int*);
typedef int (__cdecl *INFO)(void*,AdapterInfo*,int);
typedef int (__cdecl *METRICS)(void*,int,ADLPMLogDataOutput*);
static void* __stdcall allocate(int n){return n>0&&n<1024*1024?malloc((size_t)n):NULL;}
static void text(const char*s){putchar('"');for(const unsigned char*p=(const unsigned char*)s;*p;p++){if(*p=='"'||*p=='\\')putchar('\\');if(*p>=32)putchar(*p);}putchar('"');}
static int trusted(const wchar_t*path){GUID action={0x00aac56b,0xcd44,0x11d0,{0x8c,0xc2,0,0xc0,0x4f,0xc2,0x95,0xee}};WINTRUST_FILE_INFO f={0};f.cbStruct=sizeof(f);f.pcwszFilePath=path;WINTRUST_DATA d={0};d.cbStruct=sizeof(d);d.dwUIChoice=WTD_UI_NONE;d.dwUnionChoice=WTD_CHOICE_FILE;d.pFile=&f;d.dwStateAction=WTD_STATEACTION_VERIFY;d.dwProvFlags=WTD_CACHE_ONLY_URL_RETRIEVAL;LONG code=WinVerifyTrust((HWND)INVALID_HANDLE_VALUE,&action,&d);d.dwStateAction=WTD_STATEACTION_CLOSE;WinVerifyTrust((HWND)INVALID_HANDLE_VALUE,&action,&d);return code==0;}
static void metric(ADLPMLogDataOutput*d,const char*key,int sensor,int low,int high,int multiplier){printf(",\"%s\":",key);if(sensor>=0&&sensor<ADL_PMLOG_MAX_SENSORS&&d->sensors[sensor].supported&&d->sensors[sensor].value>=low&&d->sensors[sensor].value<=high)printf("%lld",(long long)d->sensors[sensor].value*multiplier);else printf("null");}
static DWORD WINAPI owner_watch(LPVOID parent){WaitForSingleObject((HANDLE)parent,15000);TerminateProcess(GetCurrentProcess(),124);return 0;}
int main(int argc,char**argv){
 if(argc==2){char*end=NULL;unsigned long pid=strtoul(argv[1],&end,10);if(!pid||!end||*end){puts("[]");return 1;}HANDLE parent=OpenProcess(SYNCHRONIZE,FALSE,(DWORD)pid);if(!parent){puts("[]");return 1;}HANDLE thread=CreateThread(NULL,0,owner_watch,parent,0,NULL);if(!thread){CloseHandle(parent);puts("[]");return 1;}CloseHandle(thread);}

 wchar_t path[32768];UINT n=GetSystemDirectoryW(path,32768);if(!n||n>32740){puts("[]");return 0;}wcscat(path,L"\\atiadlxx.dll");if(GetFileAttributesW(path)==INVALID_FILE_ATTRIBUTES||!trusted(path)){puts("[]");return 0;}
 HMODULE dll=LoadLibraryExW(path,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);if(!dll){puts("[]");return 0;}
 CREATE create=NULL;DESTROY destroy=NULL;NUMBER number=NULL;INFO info=NULL;METRICS metrics=NULL;
 /* Copy the Windows procedure representation into the typed pointer; no incompatible call casts. */
#define RESOLVE(variable,symbol) do{FARPROC address=GetProcAddress(dll,symbol);_Static_assert(sizeof(variable)==sizeof(address),"Windows function pointer ABI");memcpy(&(variable),&address,sizeof(variable));}while(0)
 RESOLVE(create,"ADL2_Main_Control_Create");RESOLVE(destroy,"ADL2_Main_Control_Destroy");RESOLVE(number,"ADL2_Adapter_NumberOfAdapters_Get");RESOLVE(info,"ADL2_Adapter_AdapterInfo_Get");RESOLVE(metrics,"ADL2_New_QueryPMLogData_Get");
#undef RESOLVE
 void*ctx=NULL;int count=0,first=1;if(!create||!destroy||!number||!info||!metrics||create(allocate,1,&ctx)!=ADL_OK||!ctx){FreeLibrary(dll);puts("[]");return 0;}
 printf("[");if(number(ctx,&count)==ADL_OK&&count>0&&count<=64){AdapterInfo*adapters=calloc((size_t)count,sizeof(AdapterInfo));if(adapters){for(int i=0;i<count;i++)adapters[i].iSize=sizeof(AdapterInfo);if(info(ctx,adapters,count*sizeof(AdapterInfo))==ADL_OK){for(int i=0,emitted=0;i<count&&emitted<16;i++){
 AdapterInfo*a=&adapters[i];if(!a->iPresent||!a->iExist||(a->iVendorID!=1002&&a->iVendorID!=0x1002))continue;int repeated=0;for(int j=0;j<i;j++)if(adapters[j].iPresent&&adapters[j].iBusNumber==a->iBusNumber&&adapters[j].iDeviceNumber==a->iDeviceNumber&&adapters[j].iFunctionNumber==a->iFunctionNumber)repeated=1;if(repeated)continue;
 ADLPMLogDataOutput data={0};data.size=sizeof(data);if(metrics(ctx,a->iAdapterIndex,&data)!=ADL_OK)continue;char name[1024]={0};wchar_t wide[512]={0};a->strAdapterName[ADL_MAX_PATH-1]=0;if(!MultiByteToWideChar(CP_ACP,0,a->strAdapterName,-1,wide,512)||!WideCharToMultiByte(CP_UTF8,0,wide,-1,name,1024,NULL,NULL))strcpy(name,"AMD GPU");name[1023]=0;
 if(!first)putchar(',');first=0;emitted++;printf("{\"source\":\"AMD ADL\",\"vendor\":\"AMD\",\"name\":");text(name);printf(",\"key\":\"adl-pci-%d-%d-%d\"",a->iBusNumber,a->iDeviceNumber,a->iFunctionNumber);
 metric(&data,"temperature_c",PMLOG_TEMPERATURE_EDGE,0,150,1);metric(&data,"hotspot_c",PMLOG_TEMPERATURE_HOTSPOT,0,150,1);metric(&data,"core_mhz",PMLOG_CLK_GFXCLK,0,20000,1);metric(&data,"memory_mhz",PMLOG_CLK_MEMCLK,0,50000,1);metric(&data,"load",PMLOG_INFO_ACTIVITY_GFX,0,100,1);metric(&data,"fan_percent",PMLOG_FAN_PERCENTAGE,0,100,1);metric(&data,"fan_rpm",PMLOG_FAN_RPM,0,20000,1);metric(&data,"power_mw",PMLOG_ASIC_POWER,0,2000,1000);putchar('}');
 }}}free(adapters);}
 puts("]");destroy(ctx);FreeLibrary(dll);return 0;
}
