import setuptools, os

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

build_number = os.getenv('BUILD_NUMBER') or '0'

setuptools.setup(
    name="tscutter",
    version=f"0.1.{build_number}",
    author="poke30744",
    author_email="poke30744@gmail.com",
    description="Cut MEPG TS files into clips",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/poke30744/tscutter/blob/main/README.md",
    packages=setuptools.find_packages(exclude=['tests',]),
    install_requires=[
        'pydub',
        'tqdm',
        'numpy',
        'Pillow',
        'jsonpath-ng',
    ],
    entry_points={
        'console_scripts': [
            'tscutter=tscutter.analyze:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)