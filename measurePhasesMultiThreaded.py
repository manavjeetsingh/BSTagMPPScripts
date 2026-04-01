import serial
import pandas as pd
from ribbn_scripts.hardware_api.hardware import Exciter,Tag
# from ribbn_scripts.hardware_api.hardware import Tag
import numpy as np
import time
import pickle
import os
import numpy as np
import matplotlib.pyplot as plt
import os
import multiprocessing
import datetime
import math


excTypes=["RFGen", "BladeRF", None]


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
    tagParams: dict

# Initializing dummy class since GNU radio is not installed. 
# Install the GNU radio and uncommend the real class below
class CW_TX:
    def __init__(self, f=915, g=10):
        pass
    
    def set_f(self, f): 
        pass
    
    def set_g(self, g):
        pass

# from gnuradio import gr, blocks
# import osmosdr    
# class CW_TX(gr.top_block):
#     def __init__(self, f=915, g=10):
#         gr.top_block.__init__(self, "TX1")
#         # src: const DC; snk: bladeRF
#         s = self.sk = osmosdr.sink("bladerf=0,buffers=128,buflen=8192")
#         s.set_sample_rate(1e6)
#         s.set_center_freq(f, 0)
#         s.set_gain(g, 0)
#         self.connect(blocks.vector_source_c([1+0j],True), s)

#     def set_f(self, f): # upd freq
#         self.sk.set_center_freq(f*1e6, 0)
#         print(f"changed freq: {f*1e6}")

#     def set_g(self, g):
#         self.sk.set_gain(g, 0)

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



def cal_theta(adcs, rxName, txName, cfg):
    amp = []
    phi = []
    attn = []
    for channel in adcs.keys():
        dbm = np.polyval(cfg['pv'][rxName], np.log(adcs[channel]))
        uW = np.power(10, (dbm - 30) / 10) * 1e6
        amp.append(np.sqrt(uW * 50 * 2))
        pwr = int(round(dbm, 0))
        if pwr < -30:
            pwr = -30
        elif pwr > -12:
            pwr = -12
        
        phi.append(np.polyval(cfg['s11'][txName][f'{channel};{pwr}'][0], 915))
        attn.append(np.polyval(cfg['s11'][txName][f'{channel};{pwr}'][1], 915))

    h = []
    for a, p in zip(attn, phi):
        h.append([1, a * np.cos(p), a * np.sin(p)])
    # print("****************************************************")
    # print(h)
    out = np.matmul(np.matmul(np.linalg.inv(np.matmul(np.transpose(h), h)), np.transpose(h)), amp)
    theta_rad = math.atan2(out[2], out[1])
    theta_deg = np.rad2deg(math.atan2(out[2], out[1]))
    V = out[0]
    beta = math.sqrt(out[1] * out[1] + out[2] * out[2]) 
    
    return theta_deg

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
    elif params.excType==1:
        params.excObj.set_g(params.exc_power)
    elif params.excType==2:
        pass
        
    exp_no=params.epoch
    
    
    t_start=time.time()
    premature_stop=0
    premature_stop_error=""
    FREQS_DONE=[]
    # DF=pd.DataFrame(columns=["Rx","Tx", "MPP Start Time (s)",
    #                           "MPP Stop Time (s)","Voltages (mV)",
    #                             "Frequency (MHz)", "Run Exp Num", "NumMPPs"])
    
    DF=pd.DataFrame(columns=["title", "date_", "frequency", "routeA", "ab_Voltages (mV)", "ab_amp_median",  "ab_amp_all",
                             "routeA MPP Start Time (s)", "routeA MPP Stop Time (s)", "theta_ab_deg",
                             "routeB", "ba_Voltages (mV)", "ba_amp_median", "ba_amp_all", "routeB MPP Start Time (s)", 
                             "routeB MPP Stop Time (s)", "theta_ba_deg", "theta", "epoch",])
    
    DF_SNAPSHOP=DF


    try:
        for freq in freq_range:
            if params.excType==0:
                params.excObj.set_freq(freq)
            elif params.excType==1:
                params.excObj.set_f(freq)
            elif params.excType==2:
                pass
                
            print("FREQ:",freq)

            voltage_readings_1, mpp_start_time_1, mpp_stop_time_1=MPP(cmdq_rx=cmd_q1, cmdq_tx=cmd_q2, result_q=result_q)
            print(mpp_start_time_1, mpp_stop_time_1)
            voltage_readings_2, mpp_start_time_2, mpp_stop_time_2=MPP(cmdq_rx=cmd_q2, cmdq_tx=cmd_q1, result_q=result_q)
            print(mpp_start_time_2, mpp_stop_time_2)
            
            # saving entries in raw data csv
            ver_lines=[]
            phes=[1,3,4,6,7,8]
            for i in range(len(phes)):
                ver_lines.append(20.3*(i)) #this number is hardcoded, change it if the tag code is changed.
            
            median_voltages_1={}
            all_ch_voltages_1={}
            median_voltages_2={}
            all_ch_voltages_2={}
            
            # plt.subplot(1,2,1)
            # plt.plot(voltage_readings_1)
            # for idx,v in enumerate(ver_lines):
            #     plt.axvline(x = v, color = 'b', label = 'axvline - full height')
            # plt.subplot(1,2,2)
            # plt.plot(voltage_readings_2)
            # for idx,v in enumerate(ver_lines):
            #     plt.axvline(x = v, color = 'b', label = 'axvline - full height')
            # plt.show()
            
            for idx,v in enumerate(ver_lines):
                cur_idx=int(np.round(v))
                if idx!=len(ver_lines)-1:
                    n_idx = int(np.round(ver_lines[idx+1]))
                    print(f"Phase {phes[idx]} median: {np.median(voltage_readings_1[cur_idx:n_idx])}; all:{voltage_readings_1[cur_idx:n_idx]}")
                    median_voltages_1[phes[idx]]=np.median(voltage_readings_1[cur_idx:n_idx])
                    all_ch_voltages_1[phes[idx]]=voltage_readings_1[cur_idx:n_idx]
                    
                    median_voltages_2[phes[idx]]=np.median(voltage_readings_2[cur_idx:n_idx])
                    all_ch_voltages_2[phes[idx]]=voltage_readings_2[cur_idx:n_idx]
                    
                else:
                    print(f"Phase {phes[idx]} median: {np.median(voltage_readings_2[cur_idx:])}; all:{voltage_readings_2[cur_idx:]}")
                    median_voltages_1[phes[idx]]=np.median(voltage_readings_1[cur_idx:])
                    all_ch_voltages_1[phes[idx]]=voltage_readings_1[cur_idx:]
                    
                    median_voltages_2[phes[idx]]=np.median(voltage_readings_2[cur_idx:])
                    all_ch_voltages_2[phes[idx]]=voltage_readings_2[cur_idx:]

            
            thetaA_deg = cal_theta(median_voltages_1, params.tag1Name, params.tag2Name, params.tagParams)
            thetaB_deg = cal_theta(median_voltages_2, params.tag2Name, params.tag1Name, params.tagParams)
            print("*"*10)
            print(thetaA_deg, thetaB_deg, ((thetaA_deg+thetaB_deg)/2)%180)
            # saving the entry in phase csv
            entry={
                "title":"check",
                "date_": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "frequency":freq, 
                "routeA":f"{params.tag2Name}->{params.tag1Name}", 
                "ab_Voltages (mV)":voltage_readings_1,
                "ab_amp_median": list(median_voltages_1.values()),  
                "ab_amp_all": all_ch_voltages_1,
                "routeA MPP Start Time (s)":mpp_start_time_1, 
                "routeA MPP Stop Time (s)":mpp_stop_time_1, 
                "theta_ab_deg": thetaA_deg,
                "routeB":f"{params.tag1Name}->{params.tag2Name}", 
                "ba_Voltages (mV)":voltage_readings_2,
                "ba_amp_median": list(median_voltages_2.values()), 
                "ba_amp_all": mpp_start_time_2,
                "routeB MPP Start Time (s)":mpp_start_time_2, 
                "routeB MPP Stop Time (s)":mpp_stop_time_2, 
                "theta_ba_deg": thetaB_deg,
                "theta": ((thetaA_deg+thetaB_deg)/2)%np.rad2deg(np.pi),
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
    DF_SNAPSHOP.to_csv(save_path, mode='a', index=False, header=(not file_exists))
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
    elif params.excType==2:
        pass
    return premature_stop_error



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



def test(excObj, EXC_POWER, excType):
    if excType==0:
        excObj.set_pwr(EXC_POWER)
        excObj.set_freq(915)
    elif excType==1:
        excObj.set_g(EXC_POWER)
        excObj.set_f(915)
    elif excType==2:
        pass
        
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
  python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 13 --csv-path ./results.csv --freq-start 900 --freq-stop 950 --freq-step 5
  python measurePhasesMultiThreaded.py --tag1-com /dev/ttyUSB0 --tag2-com /dev/ttyUSB1 --exc-power 10 --exc-type 1 --freq-start 915 --freq-stop 935 --freq-step 10
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
        "--exc-type", type=int, default=0, choices=[0, 1, 2],
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
    parser.add_argument(
        "--csv-path", default="./test.csv",
        help="Path to save CSV results (default: ./test.csv)"
    )
    parser.add_argument(
        "--freq-start", type=int, default=915,
        help="Frequency sweep start in MHz (default: 915)"
    )
    parser.add_argument(
        "--freq-stop", type=int, default=935,
        help="Frequency sweep stop in MHz, inclusive (default: 935)"
    )
    parser.add_argument(
        "--freq-step", type=int, default=10,
        help="Frequency sweep step size in MHz (default: 10)"
    )
    parser.add_argument(
        "--config", default="Old Code/config.cal",
        help="Path to calibration file (default: Old Code/config.cal)"
    )
    args = parser.parse_args()

    with open(args.config, 'rb') as f:
        tag_parameters = pickle.load(f)
    excType = args.exc_type
    tag1Name = args.tag1_name
    tag2Name = args.tag2_name
    exc_pow = args.exc_power
    tag1Com = args.tag1_com
    tag2Com = args.tag2_com
    csv_path = args.csv_path
    freq_start = args.freq_start
    freq_stop = args.freq_stop
    freq_step = args.freq_step

    if excType==0:
        excObj = Exciter()
    elif excType==1:
        excObj = CW_TX()
        excObj.start()
    elif excType==2:
        excObj=None
        pass
    else:
        raise Exception("Incorrect exciter type")
    
    
    
    initialize(tag1Com, tag2Com)
    test(excObj, exc_pow, excType)
    
    try:
        for epoch in range(100):
            params = ExpParams()
            params.epoch = epoch
            params.tagParams = tag_parameters
            params.excType=excType
            params.exc_power = exc_pow
            params.excObj = excObj
            params.tag1Name = tag1Name
            params.tag2Name = tag2Name
            params.csvSavePath = csv_path
            params.freq_range_start = freq_start
            params.freq_range_interval = freq_step
            params.freq_range_stop = freq_stop + freq_step  # +step to make stop inclusive
            print(MPPNetReq(params))
            input("Press enter to continue...")
    finally:
        if excType==1:
            excObj.stop()
            excObj.wait()
    