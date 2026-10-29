"""Native macOS Keychain backend, isolated from other platforms."""
import ctypes as C
import sys



class Keychain:
    def __init__(self):
        if sys.platform != 'darwin':
            raise ValueError('当前平台尚未支持安全密钥存储（目前仅支持 macOS 钥匙串）')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.sec = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        p = C.c_void_p
        for name, restype, args in [
            ('CFStringCreateWithCString', p, [p, C.c_char_p, C.c_uint32]),
            ('CFDataCreate', p, [p, p, C.c_long]),
            ('CFDictionaryCreateMutable', p, [p, C.c_long, p, p]),
            ('CFDictionarySetValue', None, [p, p, p]),
            ('CFDataGetLength', C.c_long, [p]), ('CFDataGetBytePtr', p, [p]), ('CFRelease', None, [p])]:
            f = getattr(self.cf, name); f.restype = restype; f.argtypes = args
        for name, args in [('SecItemCopyMatching', [p, C.POINTER(p)]), ('SecItemAdd', [p, C.POINTER(p)]), ('SecItemUpdate', [p, p]), ('SecItemDelete', [p])]:
            f = getattr(self.sec, name); f.restype = C.c_int32; f.argtypes = args

    def constant(self, name):
        return C.c_void_p.in_dll(self.sec, name).value

    def execute(self, action, service, key=None):
        owned = []
        def dictionary(values):
            obj = self.cf.CFDictionaryCreateMutable(None, 0, None, None); owned.append(obj)
            for k, value in values.items():
                if isinstance(value, str):
                    value = self.cf.CFStringCreateWithCString(None, value.encode(), 0x08000100); owned.append(value)
                elif isinstance(value, bytes):
                    value = self.cf.CFDataCreate(None, value, len(value)); owned.append(value)
                self.cf.CFDictionarySetValue(obj, self.constant(k), value)
            return obj
        try:
            values = {'kSecClass': self.constant('kSecClassGenericPassword'), 'kSecAttrService': service, 'kSecAttrAccount': 'deepseek'}
            if action == 'read':
                values['kSecReturnData'] = C.c_void_p.in_dll(self.cf, 'kCFBooleanTrue').value
            query = dictionary(values)
            result = C.c_void_p()
            if action == 'read':
                code = self.sec.SecItemCopyMatching(query, C.byref(result))
                if code == -25300:
                    return ''
                if code == 0:
                    try:
                        return C.string_at(self.cf.CFDataGetBytePtr(result), self.cf.CFDataGetLength(result)).decode()
                    finally:
                        self.cf.CFRelease(result)
            elif action == 'save':
                update = dictionary({'kSecValueData': key.encode()})
                code = self.sec.SecItemUpdate(query, update)
                if code == -25300:
                    code = self.sec.SecItemAdd(dictionary({**values, 'kSecValueData': key.encode(), 'kSecAttrLabel': 'PaperPilot · DeepSeek API Key'}), None)
            elif action == 'delete':
                code = self.sec.SecItemDelete(query)
                if code == -25300:
                    code = 0
            else:
                raise ValueError('未知密钥操作')
            if code:
                raise ValueError('系统钥匙串操作失败，请解锁登录钥匙串并允许 PaperPilot 的 Python 进程访问；密钥未更改')
            return ''
        finally:
            for obj in reversed(owned):
                self.cf.CFRelease(obj)
