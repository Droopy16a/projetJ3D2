class GlobalState:
    def __init__(self):
        self.camera = None
        self.mobNumber = 0
        self.player_id = None

    def set_camera(self, camera):
        self.camera = camera
    def get_camera(self):
        return self.camera

    def set_player_id(self, player_id):
        self.player_id = player_id
    def get_player_id(self):
        return self.player_id

    def increase_mob_number(self):
        self.mobNumber += 1
        return self.mobNumber

    def get_mob_number(self):
        return self.mobNumber

GLOBAL_STATE = GlobalState()