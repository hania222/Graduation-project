import qrcode

container_id=[1001, 1002, 1003, 1004, 1005]
for c in container_id:
    img=qrcode.make(str(c))
    img.save(f"container_{c}.png")