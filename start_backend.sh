#!/bin/bash
export LD_LIBRARY_PATH=/opt/gcc12/lib64:$LD_LIBRARY_PATH
cd /home/sugon/code/kamelab.tools/backend
nohup /home/sugon/code/kamelab.tools/backend/venv/bin/python run.py > /tmp/kamelab_backend.log 2>&1 &
echo "Backend started PID: $!"
