import serial
import numpy as np
import time
from matplotlib import pyplot as plt
from ribbn_scripts.hardware_api.hardware import Exciter,Tag
import multiprocessing

# com_port1="COM4"
com_port1="/dev/tty.usbserial-1120"

# tag1=Tag(com_port1)
# print(tag1.get_mac())

# com_port2="COM5"
com_port2="/dev/tty.usbserial-1130"

# tag2=Tag(com_port2)
# print(tag2.get_mac())


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


cmd_q1, cmd_q2, cmd_q3, result_q, process1, process2, process3\
    =None, None, None, None, None, None, None
SLEEPTIME=  0.5

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
    # process3.start


def test():
        
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


if __name__ =="__main__":
    initialize(com_port1, com_port2)
    test()

    plt.figure(figsize=(20,10))
    for rep in range(1):
        plt.subplot(2,3,rep+1)
        print("Begin reading")     
        
        cmd_q1.put("begin_reading")
        print("Starting MPP")     
        cmd_q2.put("perform_mpp")
        
        mpp_done = False
        mpp_start_time=None
        mpp_stop_time=None
        while not mpp_done:
            tag_id, res_type, data = result_q.get()
            if res_type == "mpp_times":
                mpp_start_time, mpp_stop_time = data
                mpp_done = True
        cmd_q1.put("stop_reading")

        print("Reading response")
        
        voltage_readings = None
        while voltage_readings is None:
            tag_id, res_type, data = result_q.get()
            if res_type == "voltage_readings":
                voltage_readings = data

        mpp_time_elapsed=mpp_stop_time-mpp_start_time
        plot_all_time=np.arange(0,mpp_time_elapsed,mpp_time_elapsed/len(voltage_readings))
        plot_end_time=plot_all_time[-1]
        ver_lines=[]
        # print(mpp_time_elapsed)
        for i in range(6):
            ver_lines.append(20.3*(i))

        phes=[1,3,4,6,7,8]
        for idx,v in enumerate(ver_lines):
            plt.axvline(x = v, color = 'b', label = 'axvline - full height')
            if idx!=len(ver_lines)-1:
                cur_idx=int(np.round(v))
                n_idx = int(np.round(ver_lines[idx+1]))
                print(f"Phase {phes[idx]} median: {np.median(voltage_readings[cur_idx:n_idx])}; all:{voltage_readings[cur_idx:n_idx]}")
            else:
                cur_idx=int(np.round(v))
                print(f"Phase {phes[idx]} median: {np.median(voltage_readings[cur_idx:])}; all:{voltage_readings[cur_idx:]}")

        # plt.plot(np.arange(0,mpp_time_elapsed,mpp_time_elapsed/len(voltage_readings))[:len(voltage_readings)],voltage_readings)
        plt.plot(voltage_readings)

        plt.xlabel("Time [s]")
        plt.ylabel("ADC out [mV]")
        
    plt.show()

    # %%
    print(len(voltage_readings))


