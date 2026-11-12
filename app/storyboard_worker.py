"""Render a real frame from the selected local motion template, without a GPU."""
import json
import pathlib
import subprocess
import sys
from settings import CHARACTER_DIR, CREATE_NO_WINDOW, SIZES, WORKSPACE


def render_character(project, shot, target):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    role = next(r for r in project['characters'] if r['id']==project['settings']['lead_character'])
    source = CHARACTER_DIR/role['image'].removeprefix('/characters/media/')
    width,height = SIZES[project['settings']['resolution']][project['settings']['ratio']]
    canvas = Image.new('RGB',(width,height),'#f4f2ee')
    margin=max(20,round(width*.045))
    top=max(42,round(height*.07))
    bottom=max(105,round(height*.17))
    portrait = ImageOps.contain(Image.open(source).convert('RGB'),(width-2*margin,height-top-bottom))
    # Only the layout changes on regeneration; the selected identity stays intact.
    positions=(.5,.42,.58)
    x=round((width-portrait.width)*positions[shot['revision']%3])
    canvas.paste(portrait,(x,top))
    draw=ImageDraw.Draw(canvas)
    font_path='C:/Windows/Fonts/msyh.ttc'
    title_font=ImageFont.truetype(font_path,max(17,round(min(width,height)*.034)))
    font=ImageFont.truetype(font_path,max(16,round(min(width,height)*.032)))
    draw.text((margin,round(top*.22)),role['name'],font=title_font,fill='#3c4353')
    line=''
    lines=[]
    for char in shot['text']:
        if char=='\n' or draw.textlength(line+char,font=font)>width-2*margin:
            lines.append(line);line='' if char=='\n' else char
        else:
            line+=char
    if line: lines.append(line)
    step=round(font.size*1.5)
    limit=max(1,(bottom-margin)//step)
    if len(lines)>limit:
        lines=lines[:limit];lines[-1]=lines[-1][:-1]+'…'
    for i,line in enumerate(lines):
        draw.text((margin,height-bottom+round(margin*.4)+i*step),line,font=font,fill='#354052')
    canvas.save(target)


def main():
    payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
    project, shot, target = payload['project'], payload['shot'], pathlib.Path(payload['target'])
    if project['settings'].get('source')=='character':
        render_character(project,shot,target)
        return
    template = project['settings']['template']
    source = WORKSPACE / f'outputs/motion_test/ep{template:02d}_motion.mp4'
    if not source.is_file():
        raise FileNotFoundError('动作模板文件不存在，请保留原工作区。')
    index, revision = shot['index'], shot['revision']
    moment = .25 + ((index * .43 + revision * .71) % 2.6)
    width, height = SIZES[project['settings']['resolution']][project['settings']['ratio']]
    # Variants use different real moments and framing; no text-to-image claim.
    framing = (index + revision) % 3
    crop = ['', 'crop=iw*0.90:ih*0.90:iw*0.1:0,', 'crop=iw*0.84:ih*0.84:iw*0.16:ih*0.06,'][framing]
    vf = crop + f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xebe8e2,setsar=1'
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', f'{moment:.3f}', '-i', str(source), '-vf', vf, '-frames:v', '1', str(target)], check=True, creationflags=CREATE_NO_WINDOW)


if __name__ == '__main__':
    main()
