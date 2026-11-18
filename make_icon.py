"""Generate the NEON VOID Windows application icon."""
from PIL import Image, ImageDraw


def main():
    image = Image.new("RGBA", (128, 128), (7, 13, 23, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 123, 123), radius=25, fill=(10, 18, 31, 255),
                           outline=(42, 70, 86, 255), width=3)
    draw.polygon([(64, 13), (111, 40), (111, 88), (64, 115), (17, 88), (17, 40)],
                 outline=(112, 202, 196, 255), fill=(13, 34, 46, 255), width=5)
    draw.polygon([(64, 31), (91, 64), (64, 97), (37, 64)],
                 outline=(194, 135, 171, 255), fill=(25, 34, 52, 255), width=4)
    draw.ellipse((54, 54, 74, 74), fill=(224, 226, 215, 255))
    image.save("icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)])


if __name__ == "__main__":
    main()
