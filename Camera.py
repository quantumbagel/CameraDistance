import logging
import math
import threading
from geopy.distance import geodesic
logging.basicConfig(level=logging.DEBUG)  # This line prevents the vapix API from stealing the root logger
from sensecam_control import vapix_control, vapix_config


class NullController:
    """
    A controller class to act as a test version of the main code. Used when actually_move is set to False
    """

    def __init__(self):
        self.fake_value = 0
        self.log = logging.getLogger("NullController")
        return

    def absolute_move(self, *args):
        self.fake_value += 1

        return

    def stop_recording(self, *args):
        log = self.log.getChild("fake-stop")
        log.info("stopped recording.")
        self.fake_value += 1
        return True

    def start_recording(self, *args, profile=None):
        log = self.log.getChild("fake-start")
        log.info("started recording.")
        self.fake_value += 1
        return f'fake-recording-name{self.fake_value}', 0


class Camera:
    """
    A class to handle the math for the camera's pan, tilt, and zoom
     as well as actually doing those things in real life.
    """

    def __init__(self,
                 config: dict,
                 actually_move=True,
                 disk_name='SD_DISK',
                 profile_name=None):
        """
        Initialize the values and convert to decimal if needed
        :param config: the configuration dictionary
        :param actually_move: Whether the camera should actually move or use the NullController class
        :param disk_name: the name of the disk to use for recordings
        :param profile_name: the name of the recording profile to use (None is fine)
        :return: None
        """
        self.lat = float(config['camera']['lat'])
        self.long = float(config['camera']['long'])
        self.config = config
        self.alt = config['camera']['alt']
        self.dist_xz = -1
        self.dist_y = -1
        self.dist = -1
        self.log = logging.getLogger('Camera')
        self.heading_xz = -1
        self.heading_y = -1
        self.zoom = -1
        self.drone_loc = []
        self.move = actually_move
        self.disk_name = disk_name
        self.profile_name = profile_name
        if self.move:
            self.controller = vapix_control.CameraControl(config['login']['ip'],
                                                          config['login']['username'],
                                                          config['login']['password'])
            self.media = vapix_config.CameraConfiguration(config['login']['ip'],
                                                          config['login']['username'],
                                                          config['login']['password'])
        else:
            self.controller = NullController()
            self.media = NullController()
        self.activated = False
        self.current_pan = 0
        self.current_tilt = 0
        self.current_zoom = 0
        self.current_recording_name = ''
        self.deactivating = False

    def update(self):
        """
        Calculate the zoom and heading directions via Camera.calculate_heading_directions and Camera.calculate_zoom
        :return: none
        """
        log = self.log.getChild("update")
        self.heading_xz, self.heading_y, self.dist_xz, self.dist_y = self.calculate_heading_directions()
        self.dist, self.zoom = self.calculate_zoom()
        log.debug(f'updated (pan, tilt, horiz_distance, vert_distance, distance, zoom)'
                  f' {self.heading_xz}, {self.heading_y}, {self.dist_xz}, {self.dist_y}, {self.dist}, {self.zoom}')

    def calculate_heading_directions(self):
        """
        A function to calculate the heading and distances, while also leading the camera.
        :return: The heading
        """
        log = self.log.getChild("calculate_heading")
        pi_c = math.pi / 180  # The radians -> degrees conversion factor

        camera_lat_long = [self.lat, self.long]

        # Unpack drone_loc
        lat = self.drone_loc[0]
        long = self.drone_loc[1]
        alt = self.drone_loc[2]
        vx = self.drone_loc[3]
        vy = self.drone_loc[4]
        vz = self.drone_loc[5]

        # Convert coordinates to arc lengths
        first_lat = camera_lat_long[0] * pi_c
        first_lon = camera_lat_long[1] * pi_c
        second_lat = lat * pi_c
        second_lon = long * pi_c

        # Calculate y and x differential
        y = math.sin(second_lon - first_lon) * math.cos(second_lat)
        x = (math.cos(first_lat) * math.sin(second_lat)) - (
                math.sin(first_lat) * math.cos(second_lat) * math.cos(second_lon - first_lon))

        # Calculate pan
        pre_led_heading_xz = math.atan2(y, x)

        # Calculate x/y way distances
        pre_led_dist_xz = geodesic(camera_lat_long, [lat, long]).meters
        pre_led_dist_y = alt - self.alt

        # Calculate tilt
        pre_led_heading_y = math.atan2(pre_led_dist_y, pre_led_dist_xz)

        # Calculate x, y, and z vectors
        x = math.sin(pre_led_heading_xz) * pre_led_dist_xz
        y = pre_led_dist_y
        z = math.cos(pre_led_heading_xz) * pre_led_dist_xz

        log.debug(f"Initially calculated data: "
                  f"heading_xz {pre_led_heading_xz / pi_c} "
                  f"heading_y {pre_led_heading_y / pi_c} "
                  f"dist_xz {pre_led_dist_xz} "
                  f"dist_x {x} "
                  f"dist_y {y} "
                  f"dist_z {z}")

        lead_time = self.config['camera']['lead']

        # Lead the camera (calculate new relative x, y, and z)
        # We do north/east/up, I guess DroneKit does north/east/down? This can be changed easily
        x += lead_time * vx
        y += lead_time * - vy
        z += lead_time * vz

        # Calculate new heading/distances based on new relative x, y, and z
        heading_xz = math.acos(z / math.sqrt(x ** 2 + z ** 2))
        dist_xz = math.sqrt(x ** 2 + z ** 2)
        heading_y = math.asin(y / math.sqrt(x ** 2 + y ** 2 + z ** 2))
        dist_y = y

        log.debug(f"Data after camera lead of {lead_time}s: "
                  f"heading_xz {heading_xz / pi_c} "
                  f"heading_y {heading_y / pi_c} "
                  f"dist_xz {dist_xz} "
                  f"dist_x {x} "
                  f"dist_y {y} "
                  f"dist_z {z}")

        return heading_xz / pi_c, heading_y / pi_c, dist_xz, dist_y

    def calculate_zoom(self):
        """
        A function to calculate the zoom for the camera.
        :return: the absolute distance to the drone, and the necessary zoom value
        """
        dist = math.sqrt(self.dist_xz ** 2 + self.dist_y ** 2)
        # Determine the maximum relative "size" of the drone relative to the camera
        max_dimension = max([i for i in [self.config['drone']['x'],
                                         self.config['drone']['y'],
                                         self.config['drone']['z']]])
        zoom = (dist * self.config['scale']['width']) / (self.config['scale']['dist'] * max_dimension)  # Zoom is linear
        zoom = round(((zoom - 1) / (self.config['camera']['maximum_zoom'] - 1)) * 9999)  # API takes "steps" from 0-9999
        zoom *= 1 / self.config['camera']['zoom_error']  # Account for the "fudge factor"
        return dist, zoom

    def move_camera(self, drone_loc):
        """
        A function to send the command to pan, tilt, and zoom to the camera over whatever protocol we end up using
        :param drone_loc: the location and velocity of the drone (lat, long, alt, vx, vy, vz)
        :return: none
        """
        log = self.log.getChild("move_camera")  # Get log handler
        self.drone_loc = drone_loc  # The new position of the drone
        self.update()  # Update our data about where we should go based on self.drone_loc

        if not self.activated:
            while True:
                # Start recording
                rc_name, out = self.media.start_recording(self.disk_name, profile=self.profile_name)
                if out == 1:
                    log.error(f'failed to start recording! error: {rc_name}')
                    continue
                self.current_recording_name = rc_name  # Keep track of the recording name for management purposes
                break

            self.activated = True  # Camera is now "active"
            log.info(f"Successfully started recording! id: {self.current_recording_name}")  # Inform the current rec ID

            # Check if either of the pan, tilt, or zoom is greater than their respective minimum steps
            if (abs(self.current_pan - self.heading_xz)) > self.config['camera']['min_step'] or \
                    (abs(self.current_tilt - self.heading_y)) > self.config['camera']['min_step'] or \
                    (abs(self.current_zoom - self.zoom) > self.config['camera']['min_zoom_step']):

                log.info(f'moving to (p, t, z) {self.heading_xz + self.config["camera"]["offset"]},'
                         f' {self.heading_y}, {self.zoom}')  # Show the position we move to

                # Actually tell the camera to move
                self.controller.absolute_move(self.heading_xz + self.config['camera']['offset'],
                                              self.heading_y, self.zoom)
                # Update internal class data
                self.current_pan = self.heading_xz
                self.current_tilt = self.heading_y
                self.current_zoom = self.zoom
            else:  # We don't need to move the camera
                log.debug('Step is not significant enough to move the camera. ')

    def deactivate(self, delay=0):
        """
        Deactivate the drone after a set amount of time. The threading.Timer instantiated by this function is returned
        :param delay: the amount of time until deactivation is triggered.
        """
        log = self.log.getChild("deactivate")
        log.info(f"now starting wait for {delay}s...")

        if delay:  # Start a Timer
            self.deactivating = True
            worker = threading.Timer(delay, self._deactivate_function)
            worker.start()
            return worker
        else:
            self._deactivate_function()  # Just deactivate the camera

    def _deactivate_function(self):
        """
        Force deactivate the camera. Should not be called by user.
        :return: none
        """
        log = self.log.getChild("deactivate")

        if self.current_recording_name != '':  # If we are recording, stop it
            while True:
                log.info('stopping the recording... (name=' + self.current_recording_name + ')')
                stopped = self.media.stop_recording(self.current_recording_name)  # Did we stop the recording?
                if stopped:  # We succeeded!
                    log.info('Success stopping recording!')
                    break
                else:  # We failed :(
                    log.info('failed to stop recording! retrying...')
            self.current_recording_name = ''  # We aren't recording anymore

        # Get the position we need to go to when we deactivate
        deactivate_pan = self.config['camera']['deactivate_pos']['pan']
        deactivate_tilt = self.config['camera']['deactivate_pos']['tilt']

        if not deactivate_pan:  # If not set, just use existing data
            deactivate_pan = self.current_pan
        if not deactivate_tilt:
            deactivate_tilt = self.current_tilt
        log.info(f'deactivating to (p, t) {deactivate_pan}, {deactivate_tilt}')
        self.controller.absolute_move(deactivate_pan,
                                      deactivate_tilt)  # Deactivate the camera
        # Update camera position
        self.current_pan = deactivate_pan
        self.current_tilt = deactivate_tilt

        # We are done deactivating and are not active
        self.activated = False
        self.deactivating = False
