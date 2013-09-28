#!/usr/bin/python

"""
Running on local host, listening on https over tcp and http over unix domain socket
for authentication assertions and secure temporary storage of authorization assertions
"""
import os
import struct
import socket
import SocketServer
import ssl
import threading
import tempfile
import sock2proc
import logging

SO_PEERCRED = 17

from SocketServer import TCPServer, UnixStreamServer, ThreadingMixIn, ThreadingTCPServer
from SimpleHTTPServer import SimpleHTTPRequestHandler
from sock2proc import ProcInfo
from protocol import assert_authn, assert_authz

LOCAL_PORT = 6443 
LOCAL_PATH = tempfile.gettempdir() + "/cloudauth.sk"

TLS_KEY_FILE = "./ssh_host_ecdsa_key"
TLS_CRT_FILE = "./ssh_host_ecdsa_key.crt"

HTTP_RESP_HDRS = "HTTP/1.0 %(status)s\r\nContent-type:%(ctype)s\r\nContent-length:%(clen)s\r\n\r\n"

logger = logging.getLogger("authagent")

class CloudAuthHTTPReqHandler(SimpleHTTPRequestHandler):

    is_inet = True
    is_post = True

    def service(self):

        logger.info("path = %s", self.path)

        if (self.path.startswith("/authn")) :

            proc = self.peer_proc()

            authn = assert_authn(proc)
            
            httphd = HTTP_RESP_HDRS % {"status" : "200 OK", "ctype" : "text/authn", "clen" : str(len(authn))}

            self.connection.send(httphd + authn)

        elif (self.path.startswith("/authz")) :

            proc = self.peer_proc()

            authn = assert_authn(proc)
            
            authz = assert_authz(authn)

            httphd = HTTP_RESP_HDRS % {"status" : "200 OK", "ctype" : "text/authz", "clen" : str(len(authz))}

            self.connection.send(httphd + authz)
        
        elif (self.path.startswith("/cert")) :

            cert = ""

            with open(TLS_CRT_FILE, 'rb') as fh:
                cert = fh.read()

            httphd = HTTP_RESP_HDRS % {"status" : "200 OK", "ctype" : "text/cert", "clen" : str(len(cert))}

            self.connection.send(httphd + cert)

        elif (self.path.startswith("/sign")) :
            #sign arbituary data i=...&s=...&d=....&h=...
            pass

        elif (self.path.startswith("/roles")) :

            pass

    def peer_proc(self):

        proc = None

        if (isinstance(self.client_address, str)):
            self.is_inet = False
            creds = self.connection.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i'))
            pid, euid, egid = struct.unpack('3i', creds)
            logger.info("client via AF_UNIX, pid %s, uid %s", pid, euid)
            proc = ProcInfo.pipe2proc(pid, euid)
        else:
            self.is_inet = True 
            logger.info("client via AF_INET,  %s", self.client_address)
            proc = ProcInfo.sock2proc(self.client_address)

        return proc

    def do_GET(self):
        
        self.is_post = False
        self.service()

    def do_POST(self):

        self.is_post = True 
        self.service()
 
class HttpsThread (threading.Thread):

    def __init__(self, port, isTCP):

        threading.Thread.__init__(self)
        self.port = port
        self.isTCP = isTCP 

    def run(self):

        handler = CloudAuthHTTPReqHandler

        httpd = None

        if (self.isTCP):         

            class MyThreadingTCPServer(ThreadingTCPServer):
                 def server_bind(self):
                     self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                     self.socket.bind(self.server_address)

            httpd = MyThreadingTCPServer(("", self.port), handler) #TODO "" -> localhost

            httpd.socket = ssl.wrap_socket (httpd.socket, keyfile = TLS_KEY_FILE, certfile=TLS_CRT_FILE, server_side=True)
 
        else :

            if (os.path.exists(self.port)):
                os.unlink(self.port)
            class ThreadingUsServer(ThreadingMixIn, UnixStreamServer): pass
            httpd = ThreadingUsServer(self.port, handler)

            os.chmod(self.port, 0777)

        logger.info("serving at port %s", self.port) 


        httpd.serve_forever()

# Entrance for stand-alone execution
def main():
    
    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s %(message)s', level=logging.INFO)

    logger.info("cloudauth is running.")
    
    threads = []

    threads.append(HttpsThread(LOCAL_PORT, True));
    threads.append(HttpsThread(LOCAL_PATH, False));

    #TODO create unix domain thread

    # Wait for all threads to complete
    for t in threads:
        t.start() 

    # Wait for all threads to complete
    for t in threads:
        t.join() #TODO restart if returned

    logger.info ("cloudauth is shutdown") 
 
if __name__ == "__main__":
    
    main()

