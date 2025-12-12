class GlobalState:
    def __init__(self):
        self.camera = None
    def set_camera(self, camera):
        self.camera = camera
    def get_camera(self):
        return self.camera
    
GLOBAL_STATE = GlobalState()