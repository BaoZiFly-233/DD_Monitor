import os

for fPath, _, fList in os.walk(r'J:\广汽'):
    print(fPath)
    for f in fList:
        if f.endswith('.obj'):
            f = os.path.join(fPath, f)
            print(f)