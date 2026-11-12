"""Make a conservative, separate speaker portrait when a close-up is too wide."""
from pathlib import Path


def reframe_speaker(source, destination, *, size=(576, 1024)):
    import cv2
    import numpy as np
    from PIL import Image
    from face_motion import reference_faces

    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('不能覆盖原始画面。')
    image = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('说话人画面无法读取。')
    height, width = image.shape[:2]
    faces = reference_faces(image)
    if len(faces) != 1:
        raise ValueError('近景画面的人脸数量不明确，无法自动裁切。')
    x, y, face_w, face_h = map(float, faces[0])
    if min(face_w, face_h) < 40:
        raise ValueError('原画面的人脸细节过小，无法可靠放大。')
    crop_w = min(float(width), 2.8 * face_w, height * size[0] / size[1])
    crop_h = crop_w * size[1] / size[0]
    left = max(0., min(width - crop_w, x + face_w / 2 - crop_w / 2))
    top = max(0., min(height - crop_h, y + face_h / 2 - crop_h * .33))
    if (x < left or y < top or x + face_w > left + crop_w or y + face_h > top + crop_h):
        raise ValueError('人脸位于画面边缘，无法完整裁切。')
    with Image.open(source) as image:
        result = image.convert('RGB').crop((round(left), round(top), round(left + crop_w), round(top + crop_h)))
        result = result.resize(size, Image.Resampling.LANCZOS)
        if destination.exists():
            raise FileExistsError('已有近景素材，未覆盖。')
        destination.parent.mkdir(parents=True, exist_ok=True)
        import uuid
        temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.partial')
        try:
            result.save(temporary, format='PNG')
            temporary.rename(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return {'original_face': [x, y, face_w, face_h], 'crop': [left, top, crop_w, crop_h],
            'source_pixels': [round(crop_w), round(crop_h)], 'output_size': list(size)}


def ensure_closeup(source, folder, face, native_size):
    """Keep a sufficiently large face; otherwise create a separate cached crop."""
    import hashlib
    from PIL import Image
    from director_schema import digest
    from face_motion import check_reference

    source, folder = Path(source), Path(folder)
    box = face.get('face_box')
    if not box or face.get('method') != 'detector' or box[2] >= max(64, native_size[0] * .18):
        return source, face, False
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    target = folder / (digest({'source': source_hash, 'speaker_reframe': 1}) + '.png')
    if not target.exists():
        with Image.open(source) as image:
            output_size = image.size
        reframe_speaker(source, target, size=output_size)
    # A cached file is never trusted without decoding and detecting again.
    checked = check_reference({'image': str(target), 'size': native_size})
    if checked.get('method') != 'detector' or checked['face_box'][2] < max(64, native_size[0] * .18):
        raise ValueError('自动近景的人脸仍然太小，无法继续口型制作。')
    return target, checked, True
