$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\KrolikControl'
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KrolikControl'
$start=Join-Path ([Environment]::GetFolderPath('Programs')) 'Krolik Control.lnk'
$desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Krolik Control.lnk'
$stage=$null;$previous=$null;$moved=$false;$registration=$null;$registrationStarted=$false;$setupMutex=$null;$ownsMutex=$false
function Save-Registration {
 $snapshot=@{registry=$null;shortcuts=@()}
 if(Test-Path -LiteralPath $key){
  $item=Get-Item -LiteralPath $key;$snapshot.registry=@()
  foreach($name in $item.GetValueNames()){$snapshot.registry+=@{name=$name;kind=[string]$item.GetValueKind($name);value=$item.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)}}
 }
 foreach($path in @($start,$desktop)){$exists=Test-Path -LiteralPath $path;$snapshot.shortcuts+=@{path=$path;exists=$exists;bytes=if($exists){[IO.File]::ReadAllBytes($path)}else{$null}}}
 return $snapshot
}
function Restore-Registration($snapshot) {
 if($null -eq $snapshot.registry){Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue}
 else{
  if(Test-Path -LiteralPath $key){$item=Get-Item -LiteralPath $key;foreach($name in $item.GetValueNames()){if($name -notin @($snapshot.registry|ForEach-Object{$_.name})){Remove-ItemProperty -LiteralPath $key -Name $name -ErrorAction Stop}}}
  New-Item -Path $key -Force|Out-Null
  foreach($row in $snapshot.registry){New-ItemProperty -Path $key -Name $row.name -Value $row.value -PropertyType $row.kind -Force|Out-Null}
 }
 foreach($row in $snapshot.shortcuts){if($row.exists){[IO.File]::WriteAllBytes($row.path,[byte[]]$row.bytes)}elseif(Test-Path -LiteralPath $row.path){Remove-Item -LiteralPath $row.path -Force -ErrorAction Stop}}
}
function Assert-Closed {
 $entry=[regex]::Escape((Join-Path $root 'data\main.py'))
 $active=@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction Stop|Where-Object {$_.CommandLine -match $entry})
 if($active.Count -gt 0){throw 'Закройте установленный Krolik Control и повторите действие.'}
 foreach($runtime in @('data\pythonw.exe','data\python.exe')){
  $path=Join-Path $root $runtime
  if(Test-Path -LiteralPath $path){try{$handle=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$handle.Dispose()}catch{throw 'Файлы приложения заняты. Закройте Krolik Control и повторите действие.'}}
 }
}
function Assert-Owned {
 $marker=Join-Path $root 'install-info.json'
 if(!(Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw|ConvertFrom-Json).product -ne 'KrolikControl'){throw 'Папка занята неизвестными файлами. Установка не меняла её содержимое.'}
 if((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Папка установки является ссылкой.'}
}
try {
 $setupMutex=[Threading.Mutex]::new($false,('Local\KrolikControlSetup-'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value))
 try{$ownsMutex=$setupMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$ownsMutex=$true}
 if(!$ownsMutex){throw 'Установка или удаление уже выполняется. Дождитесь окончания.'}
 Assert-Closed
 if($env:KROLIK_SETUP_MODE -eq 'uninstall'){
  Assert-Owned
  $removed=$false
  for($i=0;$i -lt 15;$i++){
   try{Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop;$removed=$true;break}catch{Start-Sleep -Milliseconds 400}
  }
  if(!$removed){throw 'Не удалось удалить файлы. Закройте приложение и повторите удаление.'}
  Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
  foreach($shortcut in @($start,$desktop)){
   if(Test-Path -LiteralPath $shortcut){$shell=New-Object -ComObject WScript.Shell;$s=$shell.CreateShortcut($shortcut);if($s.TargetPath -eq (Join-Path $root 'KrolikControl.exe')){Remove-Item -LiteralPath $shortcut -Force}}
  }
  Add-Type -AssemblyName System.Windows.Forms
  [Windows.Forms.MessageBox]::Show('Программа удалена. Личные настройки, отчёты и резервные копии сохранены.','Krolik Control')|Out-Null
  exit 0
 }
 if(Test-Path -LiteralPath $root){Assert-Owned}
 $parent=Split-Path $root;New-Item -ItemType Directory -Path $parent -Force|Out-Null
 $stage=Join-Path $parent ('.KrolikControl-stage-'+[guid]::NewGuid().ToString('N'))
 New-Item -ItemType Directory -Path $stage|Out-Null
 Expand-Archive -LiteralPath $env:KROLIK_SETUP_PAYLOAD -DestinationPath $stage -Force
 $source=Join-Path $stage 'KrolikControl'
 $manifest=Get-Content -LiteralPath (Join-Path $source 'data\release-manifest.json') -Raw|ConvertFrom-Json
 if($manifest.product -ne 'KrolikControl' -or !$manifest.files){throw 'Некорректный пакет приложения.'}
 foreach($file in $manifest.files){
  $full=[IO.Path]::GetFullPath((Join-Path $source $file.path))
  if(!$full.StartsWith($source+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Недопустимый путь в пакете.'}
  if((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $file.sha256){throw ('Файл не прошёл проверку: '+$file.path)}
 }
 $registration=Save-Registration
 if(Test-Path -LiteralPath $root){$previous=Join-Path $parent ('.KrolikControl-previous-'+[guid]::NewGuid().ToString('N'));Move-Item -LiteralPath $root -Destination $previous}
 Move-Item -LiteralPath $source -Destination $root;$moved=$true
 @{product='KrolikControl';version=$manifest.version;installed=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $root 'install-info.json') -Encoding UTF8
 $registrationStarted=$true
 New-Item -Path $key -Force|Out-Null
 $properties=@{DisplayName='Krolik Control';DisplayVersion=$manifest.version;Publisher='LeemonSun';InstallLocation=$root;DisplayIcon=(Join-Path $root 'KrolikControl.exe');UninstallString=('"'+(Join-Path $root 'data\uninstall-helper.exe')+'" /uninstall')}
 foreach($name in $properties.Keys){New-ItemProperty -Path $key -Name $name -Value $properties[$name] -PropertyType String -Force|Out-Null}
 New-ItemProperty -Path $key -Name NoModify -Value 1 -PropertyType DWord -Force|Out-Null
 New-ItemProperty -Path $key -Name NoRepair -Value 1 -PropertyType DWord -Force|Out-Null
 $shell=New-Object -ComObject WScript.Shell
 New-Item -ItemType Directory -Path (Split-Path $start) -Force|Out-Null
 $link=$shell.CreateShortcut($start);$link.TargetPath=Join-Path $root 'KrolikControl.exe';$link.WorkingDirectory=$root;$link.IconLocation=$link.TargetPath;$link.Save()
 if($env:KROLIK_SETUP_DESKTOP -eq 'yes'){$link=$shell.CreateShortcut($desktop);$link.TargetPath=Join-Path $root 'KrolikControl.exe';$link.WorkingDirectory=$root;$link.IconLocation=$link.TargetPath;$link.Save()}
 if($previous){Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue}
 exit 0
}catch{
 $message=$_.Exception.Message
 if($moved){try{Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop}catch{$message+=' Не удалось убрать незавершённую установку: '+$_.Exception.Message}}
 if($previous -and (Test-Path -LiteralPath $previous) -and !(Test-Path -LiteralPath $root)){try{Move-Item -LiteralPath $previous -Destination $root -ErrorAction Stop}catch{$message+=' Предыдущая версия сохранена в '+$previous+'. '+$_.Exception.Message}}
 if($registrationStarted){try{Restore-Registration $registration}catch{$message+=' Не удалось восстановить ярлыки или запись удаления: '+$_.Exception.Message}}
 $logdir=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'KrolikControl';New-Item -ItemType Directory -Path $logdir -Force|Out-Null
 $message|Set-Content -LiteralPath (Join-Path $logdir 'setup-error.txt') -Encoding UTF8
 if($env:KROLIK_SETUP_MODE -eq 'uninstall'){Add-Type -AssemblyName System.Windows.Forms;[Windows.Forms.MessageBox]::Show($message,'Krolik Control')|Out-Null}
 exit 1
}finally{if($stage -and (Test-Path -LiteralPath $stage)){Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue};if($setupMutex){if($ownsMutex){$setupMutex.ReleaseMutex()};$setupMutex.Dispose()}}
