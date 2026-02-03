from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import aiohttp
from PIL import Image, UnidentifiedImageError
from io import BytesIO
import time
import os
from typing import Optional

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEMS_DIR = os.path.join(BASE_DIR, "db-images")

base_image_cache = None
image_cache = {}
data_cache = {}
CACHE_TTL = 60

EXTRA_OVERLAY_URL = "https://i.ibb.co/6c8XM7WB/d1b8adf838c7bcc76c3c4ea376ee6b49-1-1-1.png"
EXTRA_OVERLAY_POS = (350, 154)
EXTRA_OVERLAY_SIZE = (312, 745)

CUSTOM_POSITIONS = {
    "203": (50, 320),
    "204": (45, 545),
    "205": (160, 750),
    "214": (805, 305),
    "211_1": (700, 120),
    "211_2": (160, 120),
    "W1": (672, 590),
    "W2": (700, 765)
}

CUSTOM_SIZES = {
    "203": (160, 160),
    "204": (170, 170),
    "205": (170, 170),
    "214": (170, 170),
    "211_1": (170, 170),
    "211_2": (170, 170),
    "W1": (320, 125),
    "W2": (150, 150)
}

DEFAULT_IMAGES = {
    "203": "https://i.ibb.co/1YSHrnyz/IMG-20260202-203237-removebg-preview.png",
    "204": "https://i.ibb.co/G4zcs79B/IMG-20260202-201819-removebg-preview-1.png",
    "205": "https://i.ibb.co/1YX2gxXr/IMG-20260202-203645-removebg-preview-1.png",
    "214": "https://i.ibb.co/dsJB9ybw/IMG-20260202-204144-removebg-preview.png",
    "211_1": "https://i.ibb.co/Fbr68cJW/IMG-20260202-202525-removebg-preview.png",
    "211_2": "https://i.ibb.co/1YSHrnyz/IMG-20260202-203237-removebg-preview.png",
    "W1": "https://i.ibb.co/rGmKJQRy/FF-M4-A1-1.png",
    "W2": "https://system.ffgarena.cloud/api/iconsff?image=90200003",
}

BASE_IMAGE_URL = "https://i.ibb.co/k2vt71sM/file-00000000d58862383add91.png"

async def fetch_data(uid: str):
    now = time.time()

    if uid in data_cache and now - data_cache[uid]["time"] < CACHE_TTL:
        return data_cache[uid]["data"]

    try:
        url = f"https://garena-supreme.nacdevs.qzz.io/info?uid={uid}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()

        if "AccountProfileInfo" not in data:
            raise ValueError("Invalid UID")

        data_cache[uid] = {"data": data, "time": now}
        return data

    except Exception as e:
        print(f"UID fetch failed: {e}")
        return None

def load_local_image(item_id):
    try:
        if not item_id:
            return None

        path = os.path.join(ITEMS_DIR, f"{item_id}.png")
        if not os.path.exists(path):
            return None

        return Image.open(path).convert("RGBA")

    except UnidentifiedImageError:
        return None


async def fetch_remote_image(url: str):
    try:
        if url in image_cache:
            return image_cache[url].copy()

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                content = await response.read()
                img = Image.open(BytesIO(content)).convert("RGBA")
                image_cache[url] = img
                return img.copy()

    except Exception:
        return None


async def fetch_image(item_id, fallback_key: Optional[str] = None):
    img = load_local_image(item_id)
    if img:
        return img

    if fallback_key and fallback_key in DEFAULT_IMAGES:
        return await fetch_remote_image(DEFAULT_IMAGES[fallback_key])

    return None


async def fetch_base():
    global base_image_cache

    if base_image_cache is None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(BASE_IMAGE_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    content = await response.read()
                    base_image_cache = Image.open(BytesIO(content)).convert("RGBA")
        except Exception:
            return None

    return base_image_cache.copy()

async def overlay_items(outfits, weapons):
    base = await fetch_base()
    if base is None:
        raise RuntimeError("Base image failed")

    overlays = []
    positions = []
    counted_211 = 0

    for item in outfits:
        sid = str(item)

        if sid.startswith("211"):
            counted_211 += 1
            key = f"211_{counted_211}"
        else:
            key = sid[:3]

        pos = CUSTOM_POSITIONS.get(key)
        size = CUSTOM_SIZES.get(key, (100, 100))
        img = await fetch_image(item, fallback_key=key)

        if img and pos:
            overlays.append(img.resize(size, Image.LANCZOS))
            positions.append(pos)

    for i in range(2):
        wid = weapons[i] if i < len(weapons) else None
        key = f"W{i+1}"
        pos = CUSTOM_POSITIONS.get(key)
        size = CUSTOM_SIZES.get(key, (100, 100))
        img = await fetch_image(wid, fallback_key=key)

        if img and pos:
            overlays.append(img.resize(size, Image.LANCZOS))
            positions.append(pos)

    for img, pos in zip(overlays, positions):
        base.paste(img, pos, img)

    extra = await fetch_remote_image(EXTRA_OVERLAY_URL)
    if extra:
        extra = extra.resize(EXTRA_OVERLAY_SIZE, Image.LANCZOS)
        base.paste(extra, EXTRA_OVERLAY_POS, extra)

    return base

@app.get("/profile")
async def api(uid: str, format: str = "png"):
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")

    fmt = format.lower()
    
    data = await fetch_data(uid)
    if not data:
        raise HTTPException(status_code=404, detail="Profile not found")

    outfits = data["AccountProfileInfo"].get("EquippedOutfit", [])
    weapons = data.get("AccountInfo", {}).get("EquippedWeapon", [])

    image = await overlay_items(outfits, weapons)
    buf = BytesIO()

    if fmt in ("jpg", "jpeg"):
        image.convert("RGB").save(buf, "JPEG")
        media_type = "image/jpeg"
    else:
        image.save(buf, "PNG")
        media_type = "image/png"

    buf.seek(0)
    return StreamingResponse(buf, media_type=media_type)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)