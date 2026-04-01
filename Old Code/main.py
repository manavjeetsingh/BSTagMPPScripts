#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""code for multi-tags"""
__author__ = "Yang Xie"
__copyright__ = "Copyright 2024, IMLab, SBU"
__version__ = "V0.0.1"
__date__ = "2024-08-20"
__email__ = "yang.xie.2@stonybrook.edu"
__memo__ = "change config.json before run"
import csv
from datetime import datetime
import math
import re
import pickle
import numpy as np
import serial
import time
import threading
from queue import Queue
import json

class Tag(threading.Thread):
    def __init__(self, port, baudrate, data_queue, name):
        super().__init__(name=name)
        self.port = serial.Serial(port, baudrate, timeout=1)
        self.data_queue = data_queue
        self.tag_name = "unknown"

    def port_open(self):
        if not self.port.is_open:
            self.port.open()

    def port_close(self):
        if self.port.is_open:
            self.port.close()

    def send_data(self, data):
        n = self.port.write((data + '\n').encode())
        print(f'{self.name}->Sent cmd: {data}, bytes written: {n}')
        return n

    def read_data(self):
        while self.port.is_open:
            message = self.port.readline().decode().strip()
            if message:
                self.data_queue.put(f"{self.tag_name};{message}")

    def run(self):
        self.read_data()

def parseMSG(q):
    item = q.get()
    if item.strip():
        print(item)
        r = item.split(";")
        return r[0], r[1]

def load_json(json_string):
    try:
        data = json.loads(json_string)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        return None
    except Exception as e:
        print(f"JSON Loading  error: {e}")
        return None

def parse_r(j):
    r_v = []
    ls = str(j['data']).split(",")
    ls.pop()
    for item in ls:
        r_v.append(float(item))
    return r_v

def read_pickle(file_path):
    with open(file_path, "rb") as fp:
        variable = pickle.load(fp)
    return variable

def get_theta(s, row, phi):
    h = []
    for row_ele, phi_ele in zip(row, phi):
        h.append([1, row_ele * np.cos(phi_ele), row_ele * np.sin(phi_ele)])
    out = np.matmul(np.matmul(np.linalg.inv(np.matmul(np.transpose(h), h)), np.transpose(h)), s)
    return out[0], math.atan2(out[2], out[1]), math.sqrt(out[1]*out[1]+out[2]*out[2])

def cal_theta(dt, cfg):
    rs = {}
    for route, adcs in dt.items():
        r = route.split("->")
        tx = r[0]
        rx = r[1]
        amp = []
        phi = []
        attn = []
        i = 1
        try:
            for adc in adcs:
                dbm = np.polyval(cfg['pv'][rx], np.log(adc))
                uW = np.power(10, (dbm - 30) / 10) * 1e6
                amp.append(np.sqrt(uW * 50 * 2))
                pwr = int(round(dbm, 0))
                if pwr < -30:
                    pwr = -30
                elif pwr > -12:
                    pwr = -12
                if i == 2:
                    i += 1
                phi.append(np.polyval(cfg['s11'][tx][f'{i};{pwr}'][0], 915))
                attn.append(np.polyval(cfg['s11'][tx][f'{i};{pwr}'][1], 915))
                i += 1

            h = []
            for a, p in zip(attn, phi):
                h.append([1, a * np.cos(p), a * np.sin(p)])
            print("****************************************************")
            print(h)
            out = np.matmul(np.matmul(np.linalg.inv(np.matmul(np.transpose(h), h)), np.transpose(h)), amp)
            res = [out[0], math.atan2(out[2], out[1]), math.atan2(out[2], out[1]) * 180 / np.pi,math.sqrt(out[1] * out[1] + out[2] * out[2])]
            rs[route] = [adcs, res]
            print(rs)
        except Exception as e1:
            print(e1)
            rs[route] = [adcs, [0.0, 0.0, 0.0, 0.0]]

    print(rs)
    return rs

if __name__ == '__main__':
    tag_name_dict = {
        #"EC:62:60:4D:34:8C": "TagV32_1",
        #"10:97:BD:D4:05:10": s"TagV32_3",
        #"C0:49:EF:08:D5:EC": "TagV32_6",
        "EC:62:60:4D:49:1C": "TagV32_8",
        "10:97:BD:D4:92:74": "TagV32_9"
        #"94:3C:C6:6D:2A:68": "TagV32_2"
        # "94:3C:C6:6D:53:5C": "TagV32_10"
        #"F4:12:FA:9F:23:54": "TagV62_3",
        #"F4:12:FA:4F:A3:38": "TagV62_5"
        
    }

    ch_list = ['ch_1', 'ch_3', 'ch_4', 'ch_5', 'ch_6', 'ch_7', 'ch_8']

    with open('C:\\Users\\SHMlab\\Documents\\Kent\\BTTN-Multi-Tags_0917\\BTTN-Multi-Tags_0917\\config.json', 'r') as file:
        config = json.load(file)

    cal_config = read_pickle('C:\\Users\\SHMlab\\Documents\\Kent\\BTTN-Multi-Tags_0917\\BTTN-Multi-Tags_0917\\config.cal')

    title = config['title']
    cw_power = config['cw_power']
    freq = config['freq']
    ports = config['port']
    baudrate = config['baudrate']
    timeout = config['timeout']
    samples = config['samples']

    print(f"title: {title}")
    print(f"cw_power: {cw_power}")
    print(f"freq: {freq}")
    print(f"Port: {ports}")
    print(f"Baudrate: {baudrate}")
    print(f"Timeout: {timeout}")
    print(f"samples: {samples}")

    q = Queue()
    tags = {}
    i = 0
    for port in ports:
        m = Tag(port, baudrate, q, f"SerialPort{i}")
        m.start()
        i += 1
        m.send_data("mac")
        time_flag_st = time.time()
        while True:
            t, r = parseMSG(q)
            if re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', r):
                tag_name = tag_name_dict.get(r, f'{r}')
                print(tag_name)
                m.tag_name = tag_name
                tags[tag_name] = m
                break

            if time.time()-time_flag_st > 5:
                raise SystemExit

    now = (datetime.now()).strftime("%Y%m%d%H%M%S")
    res_raw_path = f'C:\\Users\\SHMlab\\Documents\\Kent\\BTTN-Multi-Tags_0917\\BTTN-Multi-Tags_0917\\res\\{now}_sd_output_raw.csv'
    res_theta_path = f'C:\\Users\\SHMlab\\Documents\\Kent\\BTTN-Multi-Tags_0917\\BTTN-Multi-Tags_0917\\res\\{now}_sd_output_phase.csv'
    try:
        with open(res_raw_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["title", "date_", "tag_rx", "tag_tx", "tx_ch", "frequency", "pwr", "amp_avg", "theta", "epoch"])
        with open(res_theta_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["title","date_", "frequency", "pwr", "routeA", "theta_ab_deg", "routeB", "theta_ba_deg", "theta_avg_deg", "epoch"])
    except Exception as e:
        print(e)

    epoch = 1
    while True:
        epoch_dict = {}
        for tx_key, tx_entity in tags.items():
            tx = tx_entity
            for rx_key, rx_entity in tags.items():
                if tx_key != rx_key:
                    print(f"rx:{rx_key}: {rx_entity}")
                    rx_entity.send_data('ch_2')
            raw_dict = {}
            for ch in ch_list:
                tx.send_data(ch)
                print(f"tx->{tx_key}:{ch}")
                time.sleep(0.1)  # caution: wait tx to settle down!
                for rx_key, rx_entity in tags.items():
                    if tx_key != rx_key:
                        rx_entity.send_data('adc50')
                ##time.sleep(1)  # caution: wait for all rx ready!

                r_count = 0
                while True:
                    t, r = parseMSG(q)
                    print(f'{t},{r}')
                    if r.startswith('adc'):
                        #dt = load_json(r)
                        key = f'{tx_key}->{t}'
                        dt = r.split(':')[1].strip().split(',')
                        dt.pop()
                        dt_float = list(map(float, dt))
                        if key not in raw_dict:
                            raw_dict[key] = []
                        raw_dict[key].append(np.median(dt_float))
                        r_count += 1
                    elif r.startswith('{"'):
                        key = f'{tx_key}->{t}'
                        dt = load_json(r)
                        ds = dt['data'].split(",")
                        ds.pop()
                        dt_float = list(map(float, ds))
                        if key not in raw_dict:
                            raw_dict[key] = []
                        raw_dict[key].append(np.median(dt_float))
                        r_count += 1
                    if r_count == len(tags)-1:
                        print(raw_dict)
                        break

            rs_ls = cal_theta(raw_dict, cal_config)
            try:
                with open(res_raw_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    #["title", "date_", "tag_rx", "tag_tx", "tx_ch", "freq", "cw_power", "amp_avg", "theta", "epoch"]
                    ch = 1
                    for key, value in rs_ls.items():
                        if ch == 2:
                            ch += 1
                        row = [title, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), key.split("->")[1], key.split("->")[0], ch, freq, cw_power, value[0], value[1][2], epoch]
                        epoch_dict[key] = value[1][2]
                        writer.writerow(row)
                        ch += 1
            except Exception as e:
                print(e)

        try:
            with open(res_theta_path, 'a', newline='') as f:
                writer = csv.writer(f)
                #["title","date_", "freq", "cw_power", "routeA", "thetaA", "routeB", "thetaB", "theta_avg", "epoch"]
                #for key, value in epoch_dict.items():
                while epoch_dict:
                    key, value = epoch_dict.popitem()
                    k = key.split("->")
                    matched_key = f'{k[1]}->{k[0]}'
                    matched_value = epoch_dict.pop(matched_key, None)  # 如果键不存在，返回 None
                    if matched_value:
                        row = [title, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), freq, cw_power, key, value, matched_key, matched_value, round(((value + matched_value) / 2) % 180,2), epoch]
                        writer.writerow(row)
        except Exception as e:
            print(e)
        epoch += 1
