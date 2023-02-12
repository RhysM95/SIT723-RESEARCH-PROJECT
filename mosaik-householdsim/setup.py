from setuptools import setup, find_packages


setup(
    name='mosaik-householdsim',
    version='2.1.0',
    author='Stefan Scherfke',
    author_email='mosaik@offis.de',
    description=('A simple simulator for household profiles.'),
    long_description=(open('README.rst').read() + '\n\n' +
                      open('CHANGES.txt').read() + '\n\n' +
                      open('AUTHORS.txt').read()),
    url='https://gitlab.com/mosaik/mosaik-householdsim',
    install_requires=[
        'arrow>=1.1.0',
        'mosaik-api>=3.0',
    ],
    packages=find_packages(),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'mosaik-householdsim = householdsim.mosaik:main',
        ],
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: Scientific/Engineering',
    ],
)
