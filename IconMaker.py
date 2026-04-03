from PIL import Image

img = Image.open("myicon.png")          # ← change to your file
img = img.resize((256, 256))
img.save("icon.ico", format="ICO", sizes=[
    (16,16), (32,32), (48,48), (64,64), (128,128), (256,256)
])
print("icon.ico created!")