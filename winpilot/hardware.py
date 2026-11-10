"""Device priorities for the local inventory. No driver is chosen by class alone."""
def device_priority(device):
    category=str(device.get('category') or '').casefold()
    name=str(device.get('name') or '').casefold()
    if device.get('problem',0):return -1
    if category=='display':return 0
    if category=='processor':return 1
    if category=='system' and any(word in name for word in ('chipset','smbus','smb bus','чипсет','ryzen','management engine','platform security')):return 2
    return {'net':3,'media':4,'hdc':5,'scsiadapter':5,'diskdrive':5,'monitor':6,'keyboard':7,'mouse':7,'bluetooth':8,'printer':9,'printqueue':9,'usb':20,'hidclass':25,'audioendpoint':30,'system':80,'softwarecomponent':90,'softwaredevice':91}.get(category,50)

def ordered_devices(devices):
    return sorted(devices,key=lambda d:(device_priority(d),str(d.get('name') or '').casefold(),str(d.get('id') or '')))
