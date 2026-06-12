import google.generativeai as genai
genai.configure(api_key="AIzaSyCSTKbXgi7KZJwyN5RgQIrcXS74VlsY4HE")
print("Listing models:")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print("Error:", e)
