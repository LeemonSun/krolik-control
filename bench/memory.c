/* User-mode data-integrity test. Same pattern engine is exercised on Linux.
 * Does not claim full physical RAM coverage or a hardware fault diagnosis. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static double clock_s(void){LARGE_INTEGER a,b;QueryPerformanceCounter(&a);QueryPerformanceFrequency(&b);return (double)a.QuadPart/b.QuadPart;}
static uint64_t available(void){MEMORYSTATUSEX s={0};s.dwLength=sizeof(s);return GlobalMemoryStatusEx(&s)?s.ullAvailPhys:0;}
static void *allocate(size_t n){return VirtualAlloc(NULL,n,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);}
static void deallocate(void *p){VirtualFree(p,0,MEM_RELEASE);}
#else
#include <time.h>
#include <sys/sysinfo.h>
static double clock_s(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static uint64_t available(void){struct sysinfo s;if(sysinfo(&s))return 0;return (uint64_t)s.freeram*s.mem_unit;}
static void *allocate(size_t n){return malloc(n);}
static void deallocate(void *p){free(p);}
#endif
static uint64_t pattern(size_t i,unsigned p,uint64_t round){
 if(p==0)return 0;
 if(p==1)return UINT64_MAX;
 if(p==2)return (i&1)?UINT64_C(0xaaaaaaaaaaaaaaaa):UINT64_C(0x5555555555555555);
 if(p==3){uint64_t x=(uint64_t)i^(round*UINT64_C(0x9e3779b97f4a7c15));x^=x>>30;x*=UINT64_C(0xbf58476d1ce4e5b9);x^=x>>27;x*=UINT64_C(0x94d049bb133111eb);return x^(x>>31);}
 return UINT64_C(1)<<((i+round)%64);
}
static unsigned verify(volatile uint64_t *p,size_t n,unsigned kind,uint64_t round){
 unsigned errors=0;for(size_t i=0;i<n;i++)if(p[i]!=pattern(i,kind,round)){errors++;if(errors>=100)return errors;}return errors;
}
static int number(const char *s,unsigned *v){char *e;errno=0;unsigned long n=strtoul(s,&e,10);if(errno||!*s||*e||n>100000)return 0;*v=(unsigned)n;return 1;}
int main(int argc,char **argv){
 unsigned mb=256,seconds=30;int self=0,inject=0;
 for(int i=1;i<argc;i++){
#ifdef KC_TESTING
  if(!strcmp(argv[i],"--self-test")){self=1;continue;}
  if(!strcmp(argv[i],"--inject-error")){inject=1;continue;}
#endif
  if(i+1>=argc)return 2;
  if(!strcmp(argv[i],"--mb")){if(!number(argv[++i],&mb))return 2;}
  else if(!strcmp(argv[i],"--seconds")){if(!number(argv[++i],&seconds))return 2;}
  else return 2;
 }
 if(!self&&(mb<64||mb>2048||(seconds!=30&&seconds!=120&&seconds!=300)))return 2;
#ifdef _WIN32
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
#endif
 uint64_t avail=available(),reserve=512ULL*1024*1024;
 if(!self&&(avail<reserve+192ULL*1024*1024)){fprintf(stderr,"Insufficient available RAM\n");return 3;}
 size_t bytes=self?1024*1024:(size_t)mb*1024*1024;
 if(!self&&bytes>(avail-reserve)/3)bytes=(size_t)((avail-reserve)/3/1048576)*1048576;
 if(!self&&bytes<64ULL*1024*1024)return 3;
 volatile uint64_t *data=allocate(bytes);if(!data)return 3;
 size_t n=bytes/sizeof(*data);uint64_t rounds=0;unsigned errors=0,phases=0;int pressure=0;double start=clock_s();
 do{
  for(unsigned kind=0;kind<5;kind++){
   if(!self&&available()<128ULL*1024*1024){pressure=1;break;}
   for(size_t i=0;i<n;i++)data[i]=pattern(i,kind,rounds);
   if(inject&&kind==3)data[n/2]^=1;
   errors+=verify(data,n,kind,rounds);phases++;
   printf("{\"phase\":\"progress\",\"mb\":%zu,\"elapsed\":%.2f,\"rounds\":%llu,\"patterns\":%u,\"errors\":%u}\n",bytes/1048576,clock_s()-start,(unsigned long long)rounds,phases,errors);fflush(stdout);
   if(errors)break;
  }
  if(!errors&&!pressure)rounds++;
 }while(!self&&!errors&&!pressure&&clock_s()-start<seconds);
 printf("{\"phase\":\"result\",\"tested_mb\":%zu,\"duration_s\":%.3f,\"rounds\":%llu,\"patterns\":%u,\"errors\":%u,\"memory_pressure\":%s}\n",bytes/1048576,clock_s()-start,(unsigned long long)rounds,phases,errors,pressure?"true":"false");fflush(stdout);deallocate((void*)data);return errors?1:pressure?4:0;
}
