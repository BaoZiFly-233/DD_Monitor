from urllib.parse import unquote

from bilibili_api import Credential


def normalize_credential_data(credential_data=None, sessdata=''):
    source = credential_data or {}
    normalized = {
        'sessdata': source.get('sessdata') or source.get('SESSDATA') or sessdata or '',
        'bili_jct': source.get('bili_jct') or source.get('biliJct') or '',
        'dedeuserid': source.get('dedeuserid') or source.get('DedeUserID') or '',
        'ac_time_value': source.get('ac_time_value') or source.get('acTimeValue') or '',
        'buvid3': source.get('buvid3') or '',
        'buvid4': source.get('buvid4') or '',
    }
    if normalized['sessdata'] and '%' in normalized['sessdata']:
        normalized['sessdata'] = unquote(normalized['sessdata'])
    return normalized


def build_credential(credential_data=None, sessdata=''):
    normalized = normalize_credential_data(credential_data, sessdata=sessdata)
    if not any(normalized.values()):
        return None
    return Credential(**normalized)


def credential_to_dict(credential):
    if credential is None:
        return {}
    return normalize_credential_data({
        'sessdata': getattr(credential, 'sessdata', ''),
        'bili_jct': getattr(credential, 'bili_jct', ''),
        'dedeuserid': getattr(credential, 'dedeuserid', ''),
        'ac_time_value': getattr(credential, 'ac_time_value', ''),
        'buvid3': getattr(credential, 'buvid3', ''),
        'buvid4': getattr(credential, 'buvid4', ''),
    })
