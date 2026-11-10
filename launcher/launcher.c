#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>
#include <stdlib.h>
#include <string.h>
/* Native launcher. Runtime is bundled locally; nothing is downloaded. */
static void fail(const wchar_t *text){MessageBoxW(NULL,text,L"Krolik Control",MB_ICONERROR|MB_OK);}
static int append(wchar_t *out,size_t capacity,const wchar_t *text){size_t a=wcslen(out),b=wcslen(text);if(a+b+1>=capacity)return 0;memcpy(out+a,text,(b+1)*sizeof(wchar_t));return 1;}
/* Windows CRT argument quoting, including trailing backslashes. */
static int argument(wchar_t *out,size_t capacity,const wchar_t *arg){
 if(!append(out,capacity,L" \""))return 0;size_t slashes=0;
 for(const wchar_t *p=arg;;p++){
  if(*p==L'\\'){slashes++;continue;}
  if(*p==L'"'||!*p){for(size_t i=0;i<slashes*2;i++)if(!append(out,capacity,L"\\"))return 0;if(*p==L'"'&&!append(out,capacity,L"\\"))return 0;}
  else for(size_t i=0;i<slashes;i++)if(!append(out,capacity,L"\\"))return 0;
  slashes=0;if(!*p)break;wchar_t c[2]={*p,0};if(!append(out,capacity,c))return 0;
 }return append(out,capacity,L"\"");
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,PWSTR ignored,int show){
 (void)instance;(void)previous;(void)ignored;(void)show;
 wchar_t self[32768],folder[32768],python[32768],entry[32768];DWORD length=GetModuleFileNameW(NULL,self,32768);
 if(!length||length>=32767){fail(L"Не удалось определить папку приложения.");return 1;}
 wcscpy(folder,self);wchar_t *last=wcsrchr(folder,L'\\');if(!last){fail(L"Некорректный путь приложения.");return 1;}*last=0;
 wcscpy(python,folder);wcscpy(entry,folder);
 if(!append(python,32768,L"\\data\\pythonw.exe")||!append(entry,32768,L"\\data\\main.py")){fail(L"Путь к приложению слишком длинный.");return 1;}
 if(GetFileAttributesW(python)==INVALID_FILE_ATTRIBUTES||GetFileAttributesW(entry)==INVALID_FILE_ATTRIBUTES){fail(L"Файлы Krolik Control не найдены. Сначала распакуйте ВЕСЬ архив. Папка data должна лежать рядом с KrolikControl.exe.");return 1;}
 wchar_t *command=calloc(32768,sizeof(wchar_t));if(!command)return 1;
 if(!argument(command,32768,python)||!append(command,32768,L" -B")||!argument(command,32768,entry)){free(command);return 1;}
 int argc=0;wchar_t **argv=CommandLineToArgvW(GetCommandLineW(),&argc);
 for(int i=1;i<argc;i++)if(!argument(command,32768,argv[i])){LocalFree(argv);free(command);fail(L"Слишком длинная командная строка.");return 1;}
 LocalFree(argv);SetEnvironmentVariableW(L"WINPILOT_EXECUTABLE",self);
 STARTUPINFOW startup={0};startup.cb=sizeof(startup);PROCESS_INFORMATION process={0};
 BOOL ok=CreateProcessW(python,command+1,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,folder,&startup,&process);free(command);
 if(!ok){wchar_t message[250];wsprintfW(message,L"Не удалось запустить Krolik Control (ошибка Windows %lu). Распакуйте весь архив в обычную папку.",GetLastError());fail(message);return 1;}
 CloseHandle(process.hThread);CloseHandle(process.hProcess);return 0;
}
