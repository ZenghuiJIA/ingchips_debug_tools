use std::os::windows::io::RawHandle;

type HANDLE = *mut std::ffi::c_void;
type BOOL = i32;
type DWORD = u32;

#[repr(C)]
struct IoCounters {
    read_operation_count: u64,
    write_operation_count: u64,
    other_operation_count: u64,
    read_transfer_count: u64,
    write_transfer_count: u64,
    other_transfer_count: u64,
}

#[repr(C)]
struct JobobjectBasicLimitInformation {
    per_process_user_time_limit: i64,
    per_job_user_time_limit: i64,
    limit_flags: DWORD,
    minimum_working_set_size: usize,
    maximum_working_set_size: usize,
    active_process_limit: DWORD,
    affinity: usize,
    priority_class: DWORD,
    scheduling_class: DWORD,
}

#[repr(C)]
struct JobobjectExtendedLimitInformation {
    basic_limit_information: JobobjectBasicLimitInformation,
    io_info: IoCounters,
    process_memory_limit: usize,
    job_memory_limit: usize,
    peak_process_memory_limit: usize,
    peak_job_memory_limit: usize,
}

const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x2000;
const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;

#[link(name = "kernel32")]
extern "system" {
    fn CreateJobObjectW(lp_job_attributes: *const std::ffi::c_void, lp_name: *const u16) -> HANDLE;
    fn SetInformationJobObject(
        h_job: HANDLE,
        job_object_info_class: i32,
        lp_job_object_info: *const std::ffi::c_void,
        cb_job_object_info_length: DWORD,
    ) -> BOOL;
    fn AssignProcessToJobObject(h_job: HANDLE, h_process: HANDLE) -> BOOL;
    fn CloseHandle(h_object: HANDLE) -> BOOL;
}

pub struct ProcessJob {
    job_handle: HANDLE,
}

unsafe impl Send for ProcessJob {}
unsafe impl Sync for ProcessJob {}

impl ProcessJob {
    pub fn new() -> Result<Self, String> {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return Err("Failed to create Win32 Job Object".to_string());
            }

            let mut info: JobobjectExtendedLimitInformation = std::mem::zeroed();
            info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let res = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                &info as *const _ as *const std::ffi::c_void,
                std::mem::size_of::<JobobjectExtendedLimitInformation>() as u32,
            );

            if res == 0 {
                CloseHandle(job);
                return Err("Failed to configure Job Object limits".to_string());
            }

            Ok(Self { job_handle: job })
        }
    }

    pub fn assign_process(&self, raw_process_handle: RawHandle) -> Result<(), String> {
        unsafe {
            let res = AssignProcessToJobObject(self.job_handle, raw_process_handle as HANDLE);
            if res == 0 {
                return Err("Failed to assign process to Job Object".to_string());
            }
            Ok(())
        }
    }
}

impl Drop for ProcessJob {
    fn drop(&mut self) {
        unsafe {
            if !self.job_handle.is_null() {
                CloseHandle(self.job_handle);
            }
        }
    }
}
