from panda3d.core import CardMaker, LColor, CollisionTraverser, CollisionNode, CollisionHandlerQueue, CollisionRay, CollisionBox, Point3, Plane, Vec3
from direct.showbase.ShowBase import ShowBase
from direct.task import Task


SNAP_DISTANCE = 1.1


class Room:
    def __init__(self, name, color):
        self.name = name
        self.color = color
        self.model = None
        self.left = None
        self.right = None
        self.corridor_left = None
        self.corridor_right = None



class Dungeon:
    def __init__(self):
        self.rooms = []
        self.visited = set()



    def add_room(self, room):
        self.rooms.append(room)


    # relie les salles et crée des couloirs entre elles
    def link_rooms(self, moved_room, render):
        if moved_room.corridor_left or moved_room.corridor_right:
            self.remove_corridor(moved_room)

        moved_room.left = None
        moved_room.right = None

        for other_room in self.rooms:
            if other_room == moved_room:
                continue

            dx = (moved_room.model.get_x() - other_room.model.get_x()) ** 2 + (moved_room.model.get_z() - other_room.model.get_z()) ** 2
            dz = abs(moved_room.model.get_z() - other_room.model.get_z())
            dist = (dx**2 + dz**2) ** 0.5
            # relie les salles en déplacant automatiquement la salle déplacée sur l'axe x de l'autre salle et à une distance de 1.2
            if dist < SNAP_DISTANCE and dz < 0.2:
                if other_room.model.get_x() < moved_room.model.get_x():
                    moved_room.left = other_room
                    other_room.right = moved_room
                    moved_room.model.set_x(other_room.model.get_x() + 1.2)
                    moved_room.model.set_z(other_room.model.get_z())
                else:
                    moved_room.right = other_room
                    other_room.left = moved_room
                    moved_room.model.set_x(other_room.model.get_x() - 1.2)
                    moved_room.model.set_z(other_room.model.get_z())
        # création des couloirs
        if moved_room.left:
            moved_room.corridor_left = self.create_corridor(render, moved_room.left, moved_room)
            moved_room.left.corridor_right = moved_room.corridor_left
        if moved_room.right:
            moved_room.corridor_right = self.create_corridor(render, moved_room, moved_room.right)
            moved_room.right.corridor_left = moved_room.corridor_right


    # crée le rectangle représentant le couloir
    def create_corridor(self, render, room_left, room_right):
        cm = CardMaker("corridor")
        cm.set_frame(0, 1, -0.15, 0.15)

        corridor = render.attach_new_node(cm.generate())
        corridor.set_color(0.6, 0.6, 0.6, 1)

        x1 = room_left.model.get_x()
        x2 = room_right.model.get_x()
        z = room_left.model.get_z()

        room_half_width = 0.5
        start_x = x1 + room_half_width
        end_x   = x2 - room_half_width

        length = max(0.01, end_x - start_x)

        corridor.set_scale(length, 1, 1)
        corridor.set_pos(start_x, 0, z)

        return corridor
    

    # retire les couloirs associés à une salle
    def remove_corridor(self, room):
        if room.corridor_left:
            room.corridor_left.remove_node()
            room.corridor_left = None
        if room.corridor_right:
            room.corridor_right.remove_node()
            room.corridor_right = None


    # verifie si le donjon est valide (pour pouvoir ensuite le sauvegarder)
    def is_valid(self):
        if not self.rooms:
            return False
         
        self.visited = set()
        start_room = self.rooms[0]
        self.dfs(start_room)
    
        return len(self.visited) == len(self.rooms)
    
    def clear_links(self):
        for room in self.rooms:
            room.left = None
            room.right = None

            if room.corridor_left:
                room.corridor_left.remove_node()
                room.corridor_left = None

            if room.corridor_right:
                room.corridor_right.remove_node()
                room.corridor_right = None
    
    def rebuild_links(self, render):
        self.clear_links()

        for room in self.rooms:
            for other in self.rooms:
                if room == other:
                    continue

                dx = abs(room.model.get_x() - other.model.get_x())
                dz = abs(room.model.get_z() - other.model.get_z())

                if dx < SNAP_DISTANCE and dz < 0.2:
                    if other.model.get_x() < room.model.get_x():
                        room.left = other
                    else:
                        room.right = other

        for room in self.rooms:
            if room.left:
                room.corridor_left = self.create_corridor(render, room.left, room)
            if room.right:
                room.corridor_right = self.create_corridor(render, room, room.right)


    # dfs (Depth-First Search), on cherche à aller au bout de chaque branche en partant de l'origine, si on a visité toutes les salles, le donjon est connecté
    def dfs(self, room):
        if room in self.visited:
            return

        self.visited.add(room)

        if room.left:
            self.dfs(room.left)

        if room.right:
            self.dfs(room.right)


# permet les controles avec la souris pour déplacer les salles, défini les noms et couleurs des salles et les affiches
class DungeonEditorApp(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.camera.set_pos(0, -10, 0)
        self.dragged_room = None

        self.dungeon = Dungeon()
        colors = [(0.8, 0.2, 0.2, 1), (0.9, 0.8, 0.1, 1), (0.2, 0.7, 0.2, 1), (0.4, 0.2, 0.8, 1)]
        names = ["Entrance", "Hallway", "Treasure", "Boss"]

        card_maker = CardMaker("room")
        card_maker.set_frame(-0.5, 0.5, -0.5, 0.5)

        total_width = (len(names) - 1) * 1.5
        start_x = - total_width / 2
        # création des salles
        for i, (name, color) in enumerate(zip(names, colors)):
            room = Room(name, color)
            room.model = self.render.attach_new_node(card_maker.generate())
            room.model.set_color(LColor(*color))
            room.model.set_pos(start_x + i * 1.5, 0, -1.5)
            self.dungeon.add_room(room)
        
        for room in self.dungeon.rooms:
            c_node = CollisionNode(f"{room.name}_cnode")
            c_node.add_solid(CollisionBox(Point3(0, 0, 0), 0.5, 0.1, 0.5))
            c_np = room.model.attach_new_node(c_node)
        # création du voyant
        cm = CardMaker("indicator")
        cm.set_frame(-0.2, 0.2, -0.2, 0.2)

        self.indicator = self.aspect2d.attach_new_node(cm.generate())
        self.indicator.set_pos(0, 0, 0.9)
        self.indicator.set_color(1, 0, 0, 1)


        self.accept("mouse1", self.on_click)
        self.accept("mouse1-up", self.on_release)
        self.taskMgr.add(self.update_drag, "dragTask")

        self.picker_ray = CollisionRay()
        picker_node = CollisionNode('mouseRay')
        picker_node.add_solid(self.picker_ray)
        picker_np = self.camera.attach_new_node(picker_node)

        self.picker_traverser = CollisionTraverser()
        self.picker_handler = CollisionHandlerQueue()
        self.picker_traverser.add_collider(picker_np, self.picker_handler)

        self.drag_plane = None
        self.drag_offset = Vec3(0)


    # permet de séléctionner les salles
    def on_click(self):
        if self.mouseWatcherNode.has_mouse():
            mpos = self.mouseWatcherNode.get_mouse()
            self.picker_ray.set_from_lens(self.camNode, mpos.get_x(), mpos.get_y())
            self.picker_traverser.traverse(self.render)

            if self.picker_handler.get_num_entries() > 0:
                self.picker_handler.sort_entries()
                picked = self.picker_handler.get_entry(0).get_into_node_path().get_parent()

                for room in self.dungeon.rooms:
                    if room.model == picked:
                        self.dragged_room = room
                        self.drag_plane = Plane(Vec3(0, 1, 0), Point3(0, 0, 0))
                        near = Point3()
                        far = Point3()
                        self.camLens.extrude(mpos, near, far)
                        near = self.render.get_relative_point(self.camera, near)
                        far = self.render.get_relative_point(self.camera, far)
                        hit = Point3()
                        if self.drag_plane.intersects_line(hit, near, far):
                            self.drag_offset = room.model.get_pos() - hit
                        else:
                            self.drag_offset = Vec3(0)

                        break


    # appelle les fonctions de vérification de liaison lorsque l'on place une salle
    def on_release(self):
        if self.dragged_room:
            self.dungeon.link_rooms(self.dragged_room, self.render)
            print("Dungeon valid:", self.dungeon.is_valid())
            self.update_validation()
        self.dragged_room = None


    # appelée à chaque frame pour détecter les mouvements de la souris et déplacer la salle séléctionné en conséquence
    def update_drag(self, task):
        if self.dragged_room and self.mouseWatcherNode.has_mouse():
            mpos = self.mouseWatcherNode.get_mouse()
            near = Point3()
            far = Point3()
            self.camLens.extrude(mpos, near, far)
            near = self.render.get_relative_point(self.camera, near)
            far = self.render.get_relative_point(self.camera, far)
            hit = Point3()
            if self.drag_plane.intersects_line(hit, near, far):
                self.dragged_room.model.set_pos(hit + self.drag_offset)

        return Task.cont
    

    # appelle les fonctions de vérification de validité du donjon et colore les salles en conséquence
    def update_validation(self):
        valid = self.dungeon.is_valid()
        color = (0, 1, 0, 1) if valid else (1, 0, 0, 1)
        self.indicator.set_color(LColor(*color))



if __name__ == "__main__":
    app = DungeonEditorApp()
    app.run()