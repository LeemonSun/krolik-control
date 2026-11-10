#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <wincrypt.h>
#include <wchar.h>
#include <stdlib.h>
#include <stdio.h>
static void message(const wchar_t *text,UINT type){MessageBoxW(NULL,text,L"Krolik Control",type);}
int WINAPI wWinMain(HINSTANCE h,HINSTANCE prev,PWSTR args,int show){(void)prev;(void)show;
 int removing=wcsstr(args,L"/uninstall")!=NULL||FindResourceW(h,MAKEINTRESOURCEW(1),RT_RCDATA)==NULL;
 if(MessageBoxW(NULL,removing?L"Удалить Krolik Control? Личные настройки, отчёты и копии драйверов сохранятся.":L"Установить Krolik Control для текущего пользователя? Программа появится в меню «Пуск» и списке установленных приложений.",L"Krolik Control",MB_OKCANCEL|MB_ICONQUESTION)!=IDOK)return 0;
 wchar_t self[32768],temp[MAX_PATH],work[MAX_PATH],payload[MAX_PATH],ps[MAX_PATH];
 if(!GetModuleFileNameW(NULL,self,32768)||!GetTempPathW(MAX_PATH,temp)||!GetTempFileNameW(temp,L"KRC",0,work)){message(L"Не удалось создать временную папку.",MB_ICONERROR);return 1;}
 DeleteFileW(work);if(!CreateDirectoryW(work,NULL))return 1;
 if(swprintf(payload,MAX_PATH,L"%ls\\package.zip",work)<0)return 1;
 HRSRC data=FindResourceW(h,MAKEINTRESOURCEW(1),RT_RCDATA);DWORD size=data?SizeofResource(h,data):0;void *bytes=data?LockResource(LoadResource(h,data)):NULL;
 if(!removing){HANDLE file=CreateFileW(payload,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_TEMPORARY,NULL);DWORD wrote=0;if(!bytes||!size||file==INVALID_HANDLE_VALUE||!WriteFile(file,bytes,size,&wrote,NULL)||wrote!=size){if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);message(L"Не удалось распаковать установщик.",MB_ICONERROR);return 1;}CloseHandle(file);}
 HRSRC script=FindResourceW(h,MAKEINTRESOURCEW(2),RT_RCDATA);DWORD script_size=script?SizeofResource(h,script):0;const char *script_bytes=script?LockResource(LoadResource(h,script)):NULL;if(!script_bytes)return 1;
 int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,script_bytes,(int)script_size,NULL,0);if(count<=0)return 1;
 wchar_t *unicode=calloc((size_t)count+1,sizeof(wchar_t));if(!unicode)return 1;MultiByteToWideChar(CP_UTF8,0,script_bytes,(int)script_size,unicode,count);
 DWORD encoded_size=0;CryptBinaryToStringW((BYTE*)unicode,(DWORD)count*2,CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,NULL,&encoded_size);wchar_t *encoded=calloc(encoded_size,sizeof(wchar_t));if(!encoded){free(unicode);return 1;}CryptBinaryToStringW((BYTE*)unicode,(DWORD)count*2,CRYPT_STRING_BASE64|CRYPT_STRING_NOCRLF,encoded,&encoded_size);free(unicode);
 if(!GetSystemDirectoryW(ps,MAX_PATH)||wcslen(ps)+52>=MAX_PATH)return 1;wcscat(ps,L"\\WindowsPowerShell\\v1.0\\powershell.exe");
 SetEnvironmentVariableW(L"KROLIK_SETUP_PAYLOAD",payload);SetEnvironmentVariableW(L"KROLIK_SETUP_SELF",self);SetEnvironmentVariableW(L"KROLIK_SETUP_MODE",removing?L"uninstall":L"install");
 if(!removing)SetEnvironmentVariableW(L"KROLIK_SETUP_DESKTOP",MessageBoxW(NULL,L"Добавить ярлык на рабочий стол?",L"Krolik Control",MB_YESNO|MB_ICONQUESTION)==IDYES?L"yes":L"no");
 size_t capacity=wcslen(encoded)+wcslen(ps)+160;wchar_t *command=calloc(capacity,sizeof(wchar_t));if(!command){free(encoded);return 1;}swprintf(command,capacity,L"\"%ls\" -NoProfile -NonInteractive -EncodedCommand %ls",ps,encoded);free(encoded);
 STARTUPINFOW startup={0};startup.cb=sizeof(startup);PROCESS_INFORMATION process={0};BOOL ok=CreateProcessW(ps,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,NULL,&startup,&process);free(command);
 if(!ok){DeleteFileW(payload);RemoveDirectoryW(work);message(L"Не удалось запустить установку. Подробности: ошибка запуска Windows PowerShell.",MB_ICONERROR);return 1;}
 CloseHandle(process.hThread);
 if(removing){CloseHandle(process.hProcess);RemoveDirectoryW(work);return 0;}
 HWND window=CreateWindowExW(WS_EX_TOPMOST,L"STATIC",L"Установка Krolik Control… Подождите.",WS_OVERLAPPED|WS_CAPTION|WS_VISIBLE, CW_USEDEFAULT,CW_USEDEFAULT,410,100,NULL,NULL,h,NULL);
 MSG msg;while(WaitForSingleObject(process.hProcess,50)==WAIT_TIMEOUT){while(PeekMessageW(&msg,NULL,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}}
 if(window)DestroyWindow(window);DWORD code=1;GetExitCodeProcess(process.hProcess,&code);CloseHandle(process.hProcess);DeleteFileW(payload);RemoveDirectoryW(work);
 if(code){message(L"Установка не завершена. Закройте Krolik Control и повторите. Сведения сохранены в %LOCALAPPDATA%\\KrolikControl\\setup-error.txt.",MB_ICONERROR);return 1;}
 message(L"Krolik Control установлен. Запускайте программу из меню «Пуск».",MB_ICONINFORMATION);return 0;
}
