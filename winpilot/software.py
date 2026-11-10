"""Full registered install inventory; immutable, single-use vendor-action previews."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

MSIX_PS=r'''@(Get-AppxPackage -ErrorAction Stop|Where-Object {!$_.IsFramework -and !$_.IsResourcePackage}|Select-Object -First 1000|ForEach-Object{@{record_id=('msix:'+$_.PackageFullName);name=$_.Name;version=[string]$_.Version;publisher=$_.Publisher;scope='user';architecture=[string]$_.Architecture;source='msix';package=$_.PackageFullName;removable=(!$_.NonRemovable);location=$_.InstallLocation}})|ConvertTo-Json -Depth 4 -Compress'''

def digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def summary(row):
    r={k:row.get(k) for k in ('record_id','name','version','publisher','scope','architecture','source','size_kb','location','architecture_source')}
    r.update(can_remove=not row.get('no_remove',False) and bool(row.get('uninstall') or row.get('quiet_uninstall') or row.get('source')=='msix' and row.get('removable')),can_repair=not row.get('no_repair',False) and bool(row.get('windows_installer') and re.fullmatch(r'\{[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}',row.get('registry_key',''))))
    return r

def split_command(command):
    import ctypes as C
    shell=C.WinDLL('shell32',use_last_error=True);kernel=C.WinDLL('kernel32');count=C.c_int()
    shell.CommandLineToArgvW.argtypes=[C.c_wchar_p,C.POINTER(C.c_int)];shell.CommandLineToArgvW.restype=C.POINTER(C.c_wchar_p);kernel.LocalFree.argtypes=[C.c_void_p]
    ptr=shell.CommandLineToArgvW(command,C.byref(count))
    if not ptr:raise ValueError('Команда удалятора не распознана')
    try:return [ptr[i] for i in range(count.value)]
    finally:kernel.LocalFree(ptr)

class SoftwareCenter:
    def __init__(self,app):self.app=app;self.rows=[];self.previews={};self.lock=threading.RLock()
    def read(self):
        if self.app.demo:
            result=[{'record_id':'demo-'+str(i),'name':name,'version':version,'publisher':'Пример издателя','scope':'user','architecture':arch,'source':'registry','uninstall':'demo.exe','registry_key':'demo','windows_installer':False,'location':'','size_kb':None} for i,(name,version,arch) in enumerate([('Firefox','140','x64'),('Firefox','115','x86'),('qBittorrent','5.0','x64'),('Steam','1.0','x64')])]
            return result,[]
        from .installed_apps import registered_apps
        notes=[];result=registered_apps(issues=notes)
        try:
            msix=self.app.backend.psjson(MSIX_PS,timeout=20)
            result+=msix if isinstance(msix,list) else [msix] if isinstance(msix,dict) and msix.get('record_id') else []
        except Exception:notes.append('Приложения Microsoft Store пока не удалось прочитать')
        seen=set();unique=[]
        for r in result:
            if r['record_id'] in seen:continue
            seen.add(r['record_id']);unique.append(r)
        return unique,notes
    def scan(self):
        rows,notes=self.read()
        return self.inventory(rows,notes)
    def inventory(self,rows,notes):
        with self.lock:self.rows=copy.deepcopy(rows)
        return {'items':[summary(r) for r in sorted(rows,key=lambda r:(r['name'].casefold(),str(r.get('architecture'))))],'notes':notes,'scanned':time.time(),'demo':self.app.demo}
    def preview(self,body):
        ident=body.get('id');action=body.get('action')
        if action not in ('remove','repair'):raise ValueError('Выберите удаление или восстановление')
        with self.lock:row=next((r for r in self.rows if r['record_id']==ident),None)
        if not row:raise ValueError('Обновите список программ')
        brief=summary(row)
        if not brief['can_remove' if action=='remove' else 'can_repair']:raise ValueError('Установка не предоставляет это действие')
        token=secrets.token_urlsafe(24)
        with self.lock:
            self.previews={token:{'expires':time.monotonic()+90,'action':action,'row':copy.deepcopy(row),'fingerprint':digest(row)}}
        return {'token':token,'name':row['name'],'version':row.get('version'),'action':action,'scope':row.get('scope'),'message':'Будет запущен штатный удалятор. Он может показать собственное окно. Личные файлы отдельно не очищаются.' if action=='remove' else 'Windows Installer попробует восстановить эту установку. Может потребоваться исходный установщик.'}
    def consume(self,body):
        if body.get('confirmed') is not True:raise ValueError('Подтвердите действие с программой')
        with self.lock:
            r=self.previews.pop(body.get('token'),None) if isinstance(body.get('token'),str) else None
            if not r or time.monotonic()>r['expires']:raise ValueError('Подтверждение устарело. Повторите выбор.')
        return r
    def execute(self,job):
        row=job['row'];rows,_=self.read();actual=next((r for r in rows if r['record_id']==row['record_id']),None)
        if not actual or digest(actual)!=job['fingerprint']:raise ValueError('Установка изменилась. Обновите список и повторите выбор.')
        if not summary(actual)['can_remove' if job['action']=='remove' else 'can_repair']:raise ValueError('Windows или издатель запретили это действие с программой')
        if self.app.demo:return {'message':'Демонстрация: программа не изменялась','verification':'demo','_inventory':self.inventory(rows,[])}
        b=self.app.backend;reboot=False
        def run(args):
            nonlocal reboot
            from .packages import ProcessError
            try:b.run(args,timeout=1200)
            except ProcessError as e:
                if e.code not in (3010,1641):raise
                reboot=True
        if row.get('scope')=='user' and b.is_admin():raise ValueError('Для изменения пользовательской установки откройте Krolik Control обычным запуском без прав администратора.')
        if row.get('source')=='msix':
            if job['action']!='remove' or not row.get('removable'):raise ValueError('Этот пакет нельзя удалить выбранным способом')
            b.ps('Remove-AppxPackage -Package $p.package -ErrorAction Stop',{'package':row['package']},timeout=600)
        elif job['action']=='repair':
            code=row.get('registry_key','')
            if not row.get('windows_installer') or not re.fullmatch(r'\{[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}',code):raise ValueError('Нет идентификатора Windows Installer')
            run([str(Path(os.environ['SystemRoot'])/'System32/msiexec.exe'),'/fa',code,'/norestart'])
        else:
            command=row.get('uninstall') or row.get('quiet_uninstall','');args=split_command(command)
            if not args or len(args)>100:raise ValueError('Штатный удалятор не распознан')
            exe=Path(os.path.expandvars(args[0]))
            if exe.name.casefold() in ('msiexec','msiexec.exe'):
                product=row.get('registry_key','')
                if not re.fullmatch(r'\{[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}',product):raise ValueError('Нет точного идентификатора MSI')
                args=[str(Path(os.environ['SystemRoot'])/'System32/msiexec.exe'),'/x',product,'/norestart']
            else:
                if not exe.is_absolute() or exe.suffix.casefold()!='.exe' or not exe.is_file() or exe.name.casefold() in ('cmd.exe','powershell.exe','pwsh.exe','rundll32.exe','mshta.exe','wscript.exe','cscript.exe'):raise ValueError('Эта установка не предоставляет безопасно распознанный EXE-удалятор')
                args[0]=str(exe)
            if any(a.lower() in ('/forcerestart','/restart','/reboot','--reboot','--restart','reboot=force') for a in args[1:]):raise ValueError('Команда удалятора требует перезагрузку. Такой запуск здесь отключён.')
            run(args)
        current,notes=self.read();present=any(r['record_id']==row['record_id'] for r in current);removed=job['action']=='remove' and not present and not notes
        return {'message':'Удаление подтверждено Windows' if removed else 'Установка ещё найдена. Закройте удалятор и обновите список.' if job['action']=='remove' and present else 'Удалятор завершился, но список программ прочитан не полностью. Обновите список для проверки.' if job['action']=='remove' else 'Команда восстановления завершена. Проверьте запуск программы.','verification':'confirmed' if removed else 'unverified','reboot_required':reboot,'_inventory':self.inventory(current,notes)}
