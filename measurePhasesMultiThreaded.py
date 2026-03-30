import serial
import pandas as pd
from ribbn_scripts.hardware_api.hardware import Exciter,Tag
import numpy as np
import time
import pickle
import os
import numpy as np
import matplotlib.pyplot as plt
import os
import multiprocessing
import datetime
from gnuradio import gr, blocks
import osmosdr


excTypes=["RFGen", "BladeRF"]

class CW_TX(gr.top_block):
    def __init__(self, f=915, g=10):
        gr.top_block.__init__(self, "TX1")
        # src: const DC; snk: bladeRF
        s = self.sk = osmosdr.sink("bladerf=0,buffers=128,buflen=8192")
        s.set_sample_rate(1e6)
        s.set_center_freq(f, 0)
        s.set_gain(g, 0)
        self.connect(blocks.vector_source_c([1+0j],True), s)

    def set_f(self, f): # upd freq
        self.sk.set_center_freq(f*1e6, 0)
        print(f"changed freq: {f*1e6}")

    def set_g(self, g):
        self.sk.set_gain(g, 0)

def device_worker(com_port, tag_id, command_queue, result_queue):
    """
    A worker function to be run in a separate PROCESS. It instantiates its
    own Tag object to avoid sharing non-serializable objects.
    """
    print(f"Process for Tag {tag_id} on {com_port} started.")
    # Each process creates its own instance of the Tag class
    tag_instance = Tag(com_port)
    
    while True:
        try:
            command = command_queue.get()

            if command == "STOP":
                tag_instance.disconnect()
                print(f"Process for Tag {tag_id} stopping.")
                break
            
            if command == "get_mac":
                result = tag_instance.get_mac()
                result_queue.put((tag_id, "mac", result))
            elif command == "begin_reading":
                tag_instance.begin_reading()
            elif command == "perform_mpp":
                result = tag_instance.perform_mpp()
                result_queue.put((tag_id, "mpp_times", result))
            elif command == "stop_reading":
                result = tag_instance.stop_reading()
                result_queue.put((tag_id, "voltage_readings", result))
            elif command == "get_adc_val":
                result = tag_instance.get_adc_val()
                result_queue.put((tag_id, "adc_vals", result))
            elif command[:2]=='ch':
                tag_instance.reflect(command.encode())

        except Exception as e:
            print(f"🛑 ERROR in process for Tag {tag_id} ({com_port}): {e}")
            continue

SLEEPTIME=0.5
READTIME=5

# Default Settings
FREQ_RANGE=list(range(775,1005,10))

# # # Setting up the exciter
exc = Exciter()
exc.set_freq(915)
exc.set_pwr(-30)

# # Connecting to Tags
# # TAG1_COM="/dev/tty.usbserial-2130"
# TAG1_COM="COM3"
# # TAG2_COM="/dev/tty.usbserial-2120"
# TAG2_COM="COM6"
# TAG3_COM="COM4"


cmd_q1, cmd_q2, cmd_q3, result_q, process1, process2, process3\
    =None, None, None, None, None, None, None

def initialize(TAG1_COM, TAG2_COM):
    global cmd_q1, cmd_q2, cmd_q3, result_q, process1, process2, process3
    
    # Create queues from the multiprocessing module
    cmd_q1 = multiprocessing.Queue()
    cmd_q2 = multiprocessing.Queue()
    # cmd_q3 = multiprocessing.Queue()
    result_q = multiprocessing.Queue()

    process1 = multiprocessing.Process(target=device_worker, args=(TAG1_COM, 1, cmd_q1, result_q), daemon=True)
    process2 = multiprocessing.Process(target=device_worker, args=(TAG2_COM, 2, cmd_q2, result_q), daemon=True)
    # process3 = multiprocessing.Process(target=device_worker, args=(TAG3_COM, 2, cmd_q3, result_q), daemon=True)

    # Start the child processes
    process1.start()
    process2.start()
    # process3.start()


def MPP(cmdq_rx,cmdq_tx, result_q):
    """
        @args: Tx, Rx: Tag type objects.
    
        - Set Rx to receiving state.
        - Go through all phases of Tx (includes non-reflecting (ch5) and receiving (ch2), for completeness.
        
        @returns a dictionary of "phase":"voltage at Rx" mappings.
    """

    cmdq_rx.put("begin_reading")
    cmdq_tx.put("perform_mpp")
    mpp_done = False
    mpp_start_time=None
    mpp_stop_time=None
    while not mpp_done:
        tag_id, res_type, data = result_q.get()
        if res_type == "mpp_times":
            mpp_start_time, mpp_stop_time = data
            mpp_done = True
    cmdq_rx.put("stop_reading")
    voltage_readings = None
    while voltage_readings is None:
        tag_id, res_type, data = result_q.get()
        if res_type == "voltage_readings":
            voltage_readings = data

    return voltage_readings, mpp_start_time, mpp_stop_time

def main(exp_no, params: ExpParams, freq_range):
    if params.excType==0:
        params.excObj.set_pwr(params.exc_power)
    elif excType==1:
        params.excObj.set_g(params.exc_power)
        
    exp_no=params.epoch
    
    
    t_start=time.time()
    premature_stop=0
    premature_stop_error=""
    FREQS_DONE=[]
    # DF=pd.DataFrame(columns=["Rx","Tx", "MPP Start Time (s)",
    #                           "MPP Stop Time (s)","Voltages (mV)",
    #                             "Frequency (MHz)", "Run Exp Num", "NumMPPs"])
    
    DF=pd.DataFrame(columns=["title", "date_", "frequency", "routeA", "ab_Voltages (mV)", 
                             "routeA MPP Start Time (s)", "routeA MPP Stop Time (s)",
                             "routeB", "ba_Voltages (mV)", "routeB MPP Start Time (s)", 
                             "routB MPP Stop Time (s)","epoch"])
    
    DF_SNAPSHOP=DF


    try:
        for freq in freq_range:
            if params.excType==0:
                params.excObj.set_freq(freq)
            elif params.excType==1:
                params.excObj.set_f(freq)
                
            print("FREQ:",freq)

            voltage_readings_1, mpp_start_time_1, mpp_stop_time_1=MPP(cmdq_rx=cmd_q1, cmdq_tx=cmd_q2, result_q=result_q)
            
            voltage_readings_2, mpp_start_time_2, mpp_stop_time_2=MPP(cmdq_rx=cmd_q2, cmdq_tx=cmd_q1, result_q=result_q)
            
            entry={
                "title":"check",
                "date_": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "frequency":freq, 
                "routeA":f"{params.tag2Name}->{params.tag1Name}", 
                "ab_Voltages (mV)":voltage_readings_1,
                "routeA MPP Start Time (s)":mpp_start_time_1, 
                "routeA MPP Stop Time (s)":mpp_stop_time_1, 
                "routeB":f"{params.tag1Name}->{params.tag2Name}", 
                "ba_Voltages (mV)":voltage_readings_2,
                "routeB MPP Start Time (s)":mpp_start_time_2, 
                "routeB MPP Stop Time (s)":mpp_stop_time_2, 
                "epoch":exp_no,
                }
            DF=pd.concat([DF,pd.DataFrame([entry])],ignore_index=True)

            FREQS_DONE.append(freq)
            DF_SNAPSHOP=DF
            
            
       
    except Exception as e:
        # Even if there is some error while running the experiments, 
        print(DF_SNAPSHOP)
        print("Had to stop script prematurely. Had the following exception: ",e)
        premature_stop=1
        premature_stop_error=e
        # raise e
            
    
    save_path=params.csvSavePath
    file_exists = os.path.isfile(save_path)
    DF_SNAPSHOP.to_csv(save_path, mode='a', index=(not file_exists))
    print(f"CSV saved/appended at: {save_path}")

    # metadata_save_path=f"{FOLDER_PATH}/metaData/{exp_no}.txt"
    # f = open(metadata_save_path, "w")
    # f.write(f"Frequencies covered: {FREQS_DONE}\n")
    # if premature_stop:
    #     f.write(f"Premature Stop: {str(premature_stop_error)}\n")
    # f.write(f"Time taken: {time_taken} seconds\n")
    # f.close()
    time_taken=time.time()-t_start

    print(f"Epoch time: {time_taken}")
   
    if params.excType==0:
        params.excObj.set_pwr(-30)
    elif excType==1:
        params.excObj.set_g(1)
    return premature_stop_error


class ExpParams:
    epoch: int
    freq_range_start: int
    freq_range_stop: int
    freq_range_interval: int
    exc_power: float
    tag1Name: str
    tag2Name: str
    csvSavePath: str
    excType: int
    excObj: any

def MPPNetReq(conf: ExpParams):
    freq_range=np.arange(conf.freq_range_start,
                        conf.freq_range_stop,
                        conf.freq_range_interval)
    err=main(exp_no=conf.epoch, params=conf,
         freq_range=freq_range,)
    if err!="":
        return {"Error Encountered": err}
    else:
        return {"Error Encountered": None}



def test(excObj, EXC_POWER):
    if excType==0:
        excObj.set_pwr(EXC_POWER)
        excObj.set_freq(915)
    else:
        excObj.set_g(EXC_POWER)
        excObj.set_f(915)
        
    # Pre-testing tags
    print("TESTING")
    
    # --- Get MAC addresses ---
    print("\nRequesting MAC addresses from devices...")
    cmd_q1.put("get_mac")
    cmd_q2.put("get_mac")

    mac_results = {}
    while len(mac_results) < 2:
        tag_id, res_type, data = result_q.get()
        if res_type == 'mac':
            print(f"✅ Main process received: MAC for Tag {tag_id} is {data}")
            mac_results[tag_id] = data

    time.sleep(SLEEPTIME)

    print("Changing phase to 1.")
    cmd_q1.put("ch_1\0\n")
    cmd_q2.put("ch_1\0\n")

    time.sleep(SLEEPTIME)
    cmd_q1.put("get_adc_val")
    cmd_q2.put("get_adc_val")
    adc_results = {}
    while len(adc_results) < 2:
        tag_id, res_type, data = result_q.get()
        if res_type == 'adc_vals':
            print(f"✅ ADC val received for tag {tag_id} is {np.median(data)}")
            adc_results[tag_id] = data

    time.sleep(SLEEPTIME)

    print("Changing phase to 2.")
    cmd_q1.put("ch_2\0\n")
    cmd_q2.put("ch_2\0\n")

    time.sleep(SLEEPTIME)
    cmd_q1.put("get_adc_val")
    cmd_q2.put("get_adc_val")
    adc_results = {}
    while len(adc_results) < 2:
        tag_id, res_type, data = result_q.get()
        if res_type == 'adc_vals':
            print(f"✅ ADC val received for tag {tag_id} is {np.median(data)}")
            adc_results[tag_id] = data

    input("Print enter to continue")
    
    return {"Test": "done"}



if __name__=="__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Measure backscatter tag phases using multi-threaded MPP sweeps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 13
  python measurePhasesMultiThreaded.py --tag1-com /dev/ttyUSB0 --tag2-com /dev/ttyUSB1 --exc-power 10 --exc-type 1
  python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 13 --tag1-name MyTagA --tag2-name MyTagB
        """,
    )
    parser.add_argument(
        "--tag1-com", required=True,
        help="COM port for tag 1 (e.g. COM2 or /dev/ttyUSB0)"
    )
    parser.add_argument(
        "--tag2-com", required=True,
        help="COM port for tag 2 (e.g. COM3 or /dev/ttyUSB1)"
    )
    parser.add_argument(
        "--exc-power", type=float, required=True,
        help="Exciter power/gain in dBm (e.g. 13)"
    )
    parser.add_argument(
        "--exc-type", type=int, default=0, choices=[0, 1],
        help="Exciter type: 0=RFGen (default), 1=BladeRF"
    )
    parser.add_argument(
        "--tag1-name", default="TagV32_9",
        help="Label for tag 1 (default: TagV32_9)"
    )
    parser.add_argument(
        "--tag2-name", default="TagV32_8",
        help="Label for tag 2 (default: TagV32_8)"
    )
    args = parser.parse_args()

    excType = args.exc_type
    tag1Name = args.tag1_name
    tag2Name = args.tag2_name
    exc_pow = args.exc_power
    tag1Com = args.tag1_com
    tag2Com = args.tag2_com

    if excType==0:
        pass
    elif excType==1:
        excObj = CW_TX()
        excObj.start()
    else:
        raise "Incorrect exciter type"
    
    
    
    initialize(tag1Com, tag2Com)
    test(excObj, exc_pow)
    
    try:
        for epoch in range(100):
            params = ExpParams()
            params.epoch = epoch
            params.excType=excType
            params.exc_power = exc_pow
            params.excObj = excObj
            params.tag1Name = tag1Name
            params.tag2Name = tag2Name
            params.freq_range_start = 805
            params.freq_range_interval = 10
            params.freq_range_stop = 935\
                +params.freq_range_interval #added to make stop range freq inclusive
            print(MPPNetReq(params))
            input("Press enter to continue...")
    finally:
        if excType==1:
            excObj.stop()
            excObj.wait()
    