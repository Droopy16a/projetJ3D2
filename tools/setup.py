import os
from setuptools import setup

os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

setup(
    name="DungeonArise",
    options={
        'build_apps': {
            'include_patterns': [
                'assets/**/*.png',
                'assets/**/*.jpg',
                'assets/**/*.env',
                'assets/**/*.mp3',
                'assets/shaders/**/*',
                'assets/**/*.glb',
                'assets/**/*.egg.pz',
                'assets/**/*.egg',
                'assets/**/*.bam',
            ],
            
            'bam_model_extensions': ['.glb', '.gltf', '.egg', '.egg.pz'],
            
            'gui_apps': {
                'DungeonArise': 'main.py',
            },
            'console_apps': {
                'DungeonAriseServer': 'server.py',
            },
            
            # 3. Forcer l'inclusion des drivers graphiques (résout le "No graphics pipe")
            'plugins': [
                'pandagl',
                'p3openal_audio',
                'p3ffmpeg', # Ajout du décodeur pour les mp3/vidéos
            ],
            
            # 4. Déclarer explicitement les packages Python tiers
            'include_modules': {
                'websockets',
                'simplepbr',
            },
            
            # 5. Plateforme cible
            'platforms': ['win_amd64'],
            'log_filename': 'runtime_log.txt',
            'log_append': False,
        }
    }
)