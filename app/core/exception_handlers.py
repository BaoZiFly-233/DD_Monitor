"""
异常捕获器
"""

import logging
import platform
import subprocess
import traceback


def uncaughtExceptionHandler(exctype, value, tb):
    logging.error(
        "\n************!!!UNCAUGHT EXCEPTION!!!*********************\n"
        + ("Type: %s" % exctype)
        + "\n"
        + ("Value: %s" % value)
        + "\n"
        + ("Traceback:" + "\n")
        + " ".join(traceback.format_tb(tb))
        + "************************************************************\n"
    )


def unraisableExceptionHandler(exc_type, exc_value, exc_traceback, err_msg, object):
    logging.error(
        "\n************!!!UNHANDLEABLE EXCEPTION!!!******************\n"
        + ("Type: %s" % exc_type)
        + "\n"
        + ("Value: %s" % exc_value)
        + "\n"
        + ("Message: %s " % err_msg)
        + "\n"
        + ("Traceback:" + "\n")
        + " ".join(traceback.format_tb(exc_traceback))
        + "\n"
        + ("On Object: %s" + str(object))
        + "\n"
        + "************************************************************\n"
    )


def threadingExceptionHandler(args):
    # Python 3.8+ threading.excepthook 只传一个 ThreadingException 对象，
    # 旧的四参数签名会导致处理器自身抛 TypeError，掩盖真正的线程异常
    exc_type, exc_value, exc_traceback, thread = args
    logging.error(
        "\n************!!!UNCAUGHT THREADING EXCEPTION!!!***********\n"
        + ("Type: %s" % exc_type)
        + "\n"
        + ("Value: %s" % exc_value)
        + "\n"
        + ("Traceback on thread %s: " % thread + "\n")
        + " ".join(traceback.format_tb(exc_traceback))
        + "************************************************************\n"
    )


def loggingSystemInfo():
    """收集系统和 GPU 信息（应在后台线程中调用）"""
    systemCmd = ""
    gpuCmd = ""
    if platform.system() == "Windows":
        systemCmd = "C:\\Windows\\System32\\systeminfo.exe"
        wmi_exe = r"C:\Windows\System32\wbem\WMIC.exe"
        gpu_property_list = "AdapterCompatibility, Caption, DeviceID, DriverDate, DriverVersion, VideoModeDescription"
        gpuCmd = f"{wmi_exe} PATH win32_VideoController GET {gpu_property_list} /FORMAT:list"
    elif platform.system() == "Darwin":
        systemCmd = "/usr/sbin/system_profiler SPHardwareDataType"
        gpuCmd = "/usr/sbin/system_profiler SPDisplaysDataType"
    elif platform.system() == "Linux":
        systemCmd = "/usr/bin/lscpu"
        gpuCmd = "/usr/bin/lspci"

    try:
        # subprocess.run 自动读取并关闭管道，避免 Popen.stdout.read() 在
        # 输出超过管道缓冲时死锁，且带超时防止 systeminfo 长时间卡住
        system_info_res = subprocess.run(
            systemCmd, shell=True, capture_output=True, text=True, timeout=20
        )
        systemInfoProcessReturn = system_info_res.stdout
        gpu_info_res = subprocess.run(
            gpuCmd, shell=True, capture_output=True, text=True, timeout=20
        )
        gpuInfoProcessReturn = gpu_info_res.stdout

        if platform.system() == "Windows":
            gpuInfoProcessReturn = gpuInfoProcessReturn.strip()
            gpuInfoProcessReturn = gpuInfoProcessReturn.replace("\n\n", "\n")

        logging.info(f"系统信息: \n{systemInfoProcessReturn}")
        logging.info(f"GPU信息: \n{gpuInfoProcessReturn}")
    except Exception:
        logging.exception("系统信息收集失败")
