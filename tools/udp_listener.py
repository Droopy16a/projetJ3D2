import socket

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

s.bind(("", 5000))
print("Listening for discovery on UDP 5000")
try:
    while True:
        data, addr = s.recvfrom(1024)
        try:
            print(addr, data.decode())
        except Exception:
            print(addr, data)
except KeyboardInterrupt:
    print('\nListener stopped')
finally:
    s.close()
