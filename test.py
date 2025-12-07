from panda3d.core import Texture
tex = Texture()
success = tex.read("C:/Users/33767/Downloads/projetJ3D2/textures/enviro.hdr")
print("Load success:", success)
if success:
    print("Texture format:", tex.getFormat())
    print("Texture size:", tex.getXSize(), tex.getYSize())