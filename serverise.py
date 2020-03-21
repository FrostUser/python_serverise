#!/usr/bin/env python2

import sys, time, pty, os

import subprocess as sp
import SocketServer
import socket, select
from threading import Thread

# Save process output and send it to newly connected clients
SAVED_OUTPUT_SIZE = 4096

def main():
    if len(sys.argv) < 3:
        print('Usage: serverise.py port command')
        exit(2)

    port = int(sys.argv[1])
    command = ' '.join(sys.argv[2:])

    server = ProcessServer(('', port), ProcessRequestHandler, command=command)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    try:
        server.proc.wait()
        print('Subprocess terminated, shutting down the server...')
    except KeyboardInterrupt:
        server.server_close()
        print('Exit')

################################################

# From cqlsh (https://github.com/elisska/cloudera-cassandra/tree/master/DATASTAX_CASSANDRA-3.5.0/pylib/cqlshlib/test/run_cqlsh.py)
# and openpty examples (https://www.programcreek.com/python/example/8151/pty.openpty)
def set_controlling_pty(master, slave):
    '''Prepare pseudo-tty on the subprocess side
    '''
    os.setsid()
    os.close(master)
    for i in range(3):
        os.dup2(slave, i)
    if slave > 2:
        os.close(slave)

class ProcessServer(SocketServer.TCPServer):
  def __init__(self, server_address, handler_class, command, **kwargs):
      '''Init TCPServer and start serverised process
      '''
      SocketServer.TCPServer.__init__(self, server_address, handler_class, **kwargs)

      # Keep process output saved
      self.saved_output = ''

      # Start subprocess inside pseudo-terminal
      master_fd, slave_fd = pty.openpty()
      preexec = (lambda: set_controlling_pty(master_fd, slave_fd))
      self.proc = sp.Popen(command, shell=True, preexec_fn=preexec,
                           stdin=None, stdout=None, stderr=None)
      self.stdin = master_fd
      self.stdout = master_fd

  def server_bind(self):
      '''Set REUSEADDR, so server can be restarted immediately
         (Otherwise, since socket stays bound for ~60 seconds,
          'cannot bind to ...' exception is thrown)
      '''
      self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      self.socket.bind(self.server_address)

class ProcessRequestHandler(SocketServer.BaseRequestHandler):
  def __init__(self, request, client_address, server):
      self.server = server
      self.proc = server.proc
      SocketServer.BaseRequestHandler.__init__(self, request, client_address, server)

  def handle(self):
      '''Handle communication between client and subprocess
      '''
      # Send previous output to new client
      self.request.sendall(self.server.saved_output)

      while True:
          if self.proc.poll() != None:
              # Subprocess terminated
              self.request.close()
              break

          readable, writable, _ = select.select([self.request, self.server.stdout], [], [])
          if self.request in readable:
              data = self.request.recv(2048)
              if len(data) < 1:
                  self.request.close()
                  break
              os.write(self.server.stdin, data)
          if self.server.stdout in readable:
              data = os.read(self.server.stdout, 2048)
              self.request.sendall(data)
              # Update saved output in the server
              self.server.saved_output += data
              # Keep only last 4096 characters
              self.server.saved_output = self.server.saved_output[-SAVED_OUTPUT_SIZE:]
          time.sleep(0.01)

################################################

if __name__ == '__main__':
    main()

