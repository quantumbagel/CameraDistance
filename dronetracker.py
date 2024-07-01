import kafka
from ruamel.yaml import YAML
import time
from Drone import Drone
from Camera import Camera
import logging


configuration = YAML().load(open("config.yml"))


def print_information(camera):
    """ A function to print some information about the drone relative to the camera
        :param camera:  object to obtain things to print from
    """
    log = logging.getLogger('print_info')
    
    log.debug(f"Distance to camera: (m) {camera.dist}")
    log.debug(f"Horizontal distance to camera: (m) {camera.dist_xz}")
    log.debug(f"Vertical distance to camera: (m) {camera.dist_y}")
    log.debug(f"Heading direction to camera: (deg) {camera.heading_xz, camera.heading_y}")


def load_config():
    """
    A function to load config.yaml and identify the latitude/longitude format
    :return: The coordinate format, in a string, and the configuration, a dictionary
    """
    y = YAML()
    config = y.load(open('config.yml'))
    config['camera_login']['lat'] = str(config['camera_login']['lat'])
    config['camera_login']['long'] = str(config['camera_login']['long'])
    if '°' not in config['camera_login']['lat']:  # decimal format
        coord_format = 'decimal'
    else:
        coord_format = 'degrees'
    return coord_format, config


def get_drone():
    """
    Wait for the drone to come alive and connect to it. Assumes we are active
    :return: the Drone
    """
    log = logging.getLogger('get_drone')
    log.info('Waiting for drone...')
    while True:
        drone = Drone(connection=configuration["kafka"]["ip"])
        if drone.consumer is None:  # Drone consumer failed connection, so we will try again
            log.info("Failed to connect to Kafka server! Trying again in 1 second...")
            time.sleep(1)
            continue
        break
    return drone




# def wait_for_record():
#     global d, c
#     while True:
#         should = should_be_recording()
#         if should == -1:  # lost drone connection
#             c.deactivate(delay=0)
#             get_drone(timeout=configuration['drone']['msg_timeout'])
#             continue
#         elif should:
#             return
#
#
# def should_be_recording():
#     log = logging.getLogger('should_be_recording')
#     mode = configuration['camera_login']['activate_method']
#     if mode == 'armed':
#         msg = d.recv_message('HEARTBEAT')
#         if msg is None:
#             return -1
#         log.debug('Checking if the drone is armed...')
#         log.debug(d.is_armed())
#         return d.is_armed()
#     if mode == 'file':
#         log.debug('Checking the file for a 1...')
#         try:
#             msg = d.recv_message('HEARTBEAT')
#             if msg is None:
#                 return -1
#             with open('record') as record_file:
#                 lines = record_file.readlines()
#                 if len(lines):
#                     if lines[0].startswith('1'):
#                         return True
#
#                 return False
#         except FileNotFoundError:
#             log.debug('The file "record" does not exist!')
#             return False
#     if mode.startswith('relative-height'):
#         height = int(mode.replace('relative-height', ''))
#         log.debug('Checking height >', height)
#         msg = d.recv_message('GLOBAL_POSITION_INT')
#         if msg is not None:
#             log.debug('Height is', msg.relative_alt / 1000, msg.alt / 1000)
#             return msg.relative_alt / 1000 > height
#         else:
#             log.debug('Failed to get message!')
#             return -1
#     else:
#         log.debug("Invalid mode: ", mode)
#         return False


active = False
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    log = logging.getLogger('Drone')
    log.warning("oh yeah")
    drone = get_drone()

    c = Camera(configuration,
                   lat_long_format="decimal",
                   actually_move=False)  # Create camera
    while True:
        drone.update_drone_position()
        lat, long, alt, vx, vy, vz = drone.lat, drone.long, drone.alt, drone.vx, drone.vy, drone.vz
        if lat is not None:
            c.move_camera([lat, long, alt])



