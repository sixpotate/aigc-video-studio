"""Speakers shipped in the installed Qwen3 CustomVoice model; no remote catalog."""
from settings import WORKSPACE
import re

VOICE_DETAILS = {
    'Vivian': {'label':'女声 · 明亮', 'native':'中文'},
    'Serena': {'label':'女声 · 温柔', 'native':'中文'},
    'Uncle_Fu': {'label':'男声 · 沉稳大叔', 'native':'中文'},
    'Dylan': {'label':'男声 · 青年京腔', 'native':'中文 · 北京口音'},
    'Eric': {'label':'男声 · 活泼川音', 'native':'中文 · 四川口音'},
    'Ryan': {'label':'男声 · 有力', 'native':'英语音色'},
    'Aiden': {'label':'男声 · 清朗', 'native':'英语音色'},
    'Ono_Anna': {'label':'女声 · 轻快', 'native':'日语音色'},
    'Sohee': {'label':'女声 · 丰富情感', 'native':'韩语音色'},
    'Robot_Low': {'label':'机械男声 · 低沉', 'native':'中文基础音色 + 机械处理', 'speaker':'Uncle_Fu', 'instruction':'清楚、稳定地逐句播报，低沉克制，像智能机器的指挥声音。', 'processing':'robot'},
    'Robot_Clear': {'label':'机械女声 · 清晰', 'native':'中文基础音色 + 机械处理', 'speaker':'Serena', 'instruction':'清晰冷静的人工智能助手声音，吐字准确，避免夸张表演。', 'processing':'robot'},
    'Creature_Low': {'label':'怪物对白 · 低哑', 'native':'中文基础音色 + 低哑处理', 'speaker':'Uncle_Fu', 'instruction':'低沉沙哑地说话，带压迫感，但每一个汉字必须清楚，不要只发出吼叫。', 'processing':'creature'},
    'Ghost_Soft': {'label':'幽灵对白 · 空灵', 'native':'中文基础音色 + 回声处理', 'speaker':'Serena', 'instruction':'低声轻缓地说话，清楚完整地说出台词，有幽远的气息。', 'processing':'ghost'},
}
VOICES = {key:value['label'] for key,value in VOICE_DETAILS.items()}
PREVIEW_DIR = WORKSPACE/'work/voice_previews'
PREVIEW_TEXT = '你好，我们的故事现在开始。'


def validate_voice(value):
    if not isinstance(value,str) or value not in VOICES:raise ValueError('请选择已安装的配音音色。')
    return value


def role_voice(role):
    voice=role.get('voice')
    if voice in VOICES:return voice
    description=' '.join(str(role.get(k,'')) for k in ('name','description','outfit','personality'))
    gender=role.get('look',{}).get('gender')
    if gender not in ('male','female'):
        gender='female' if re.search(r'女性|女子|女主|\d+岁女',description) else ('male' if re.search(r'男性|男子|男主|\d+岁男',description) else 'generic')
    if any(word in description for word in ('机器人','机械人','人工智能')):return 'Robot_Low' if gender=='male' else 'Robot_Clear'
    if any(word in description for word in ('幽灵','鬼魂')):return 'Ghost_Soft'
    return 'Dylan' if gender=='male' else 'Serena'


def generation_voice(value):
    details=VOICE_DETAILS[validate_voice(value)]
    return details.get('speaker',value),details.get('instruction','')


def process_voice(wave, sr, value):
    """Optional local timbre processing; keeps sample count and speech timing fixed."""
    import numpy as np
    from scipy import signal
    kind=VOICE_DETAILS[validate_voice(value)].get('processing')
    if not kind:return wave
    source=np.asarray(wave,dtype=np.float32);result=source.copy();t=np.arange(len(source))/sr
    if kind=='robot':
        result=signal.sosfilt(signal.butter(2,[160,4200],btype='bandpass',fs=sr,output='sos'),source)
        result*=.75+.25*np.cos(2*np.pi*65*t)
    elif kind=='creature':
        result=signal.sosfilt(signal.butter(2,2600,fs=sr,output='sos'),source)
        result=np.tanh(result*2)*.65
    if kind in ('robot','ghost'):
        for delay,gain in ((.035,.15),(.065,.1)) if kind=='robot' else ((.08,.25),(.16,.15)):
            shift=round(delay*sr)
            if len(source)>shift:result[shift:]+=source[:-shift]*gain
    result*=min(1.,.89/max(float(np.max(abs(result))),1e-6))
    return result.astype(np.float32)


def preview_shot(voice):
    return dict(id=voice,voice=validate_voice(voice),text=PREVIEW_TEXT,emotion='calm',emotion_note='',
                speed=1,pause_before=.12,pause_after=.3,duration=None)
