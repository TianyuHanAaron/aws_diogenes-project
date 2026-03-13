from tools.fetch_local_photos_tool import FetchLocalPhotosTool

tool = FetchLocalPhotosTool()
photos = tool.run(location="Sydney")

print(len(photos))
print(photos[0])