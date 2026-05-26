from setuptools import setup

setup(
    name="DungeonArise",
    options={
        'build_apps': {
            'include_patterns': [
                'assets/**/*',
                'assets/env/*.env',
                '*.py',
            ],
            'exclude_patterns': [
                'todoList.txt',
                'TECHNICAL_DOC.md',
                'README.md',
                'docs/**/*',
                'tools/**/*',
                'test.py',
                'inspect_glb.py',
                '__pycache__/**/*',
            ],
            # ---- ADD THIS TO CONVERT GLB TO BAM AUTOMATICALLY ----
            'file_handlers': {
                '*.glb': 'gltf2bam %s %s',
                '*.gltf': 'gltf2bam %s %s',
            },
            # -----------------------------------------------------
            'gui_apps': {
                'DungeonArise': 'main.py',
            },
            'console_apps': {
                'DungeonAriseServer': 'server.py',
            },
            'plugins': [
                'panda3d_bullet',
                'panda3d_opengl',
                'panda3d_openal',
                'openal',
                'pandagl',
            ],
            'include_modules': {
                '*': [
                    'simplepbr',
                ],
            },
            'platforms': [
                'win_amd64',
            ],
            'log_filename': 'runtime_log.txt',
            'log_append': False,
        }
    }
)