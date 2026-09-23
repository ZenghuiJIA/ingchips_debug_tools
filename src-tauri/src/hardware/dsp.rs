//! High-Performance Native Digital Signal Processing (DSP) Module.
//! Provides fast real-time waveform physical measurements, FFT amplitude spectrum,
//! window functions (Rectangular, Hanning, Hamming, Blackman-Harris, Flat Top),
//! and Total Harmonic Distortion (THD) calculation.

use serde::{Deserialize, Serialize};
use std::f64::consts::PI;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformMeasurements {
    pub max: f64,
    pub min: f64,
    pub vpp: f64,
    pub mean: f64,
    pub rms: f64,
    pub frequency: Option<f64>,
    pub period_sec: Option<f64>,
    pub duty_cycle_percent: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FftPoint {
    pub freq_hz: f64,
    pub magnitude: f64,
    pub db: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarmonicInfo {
    pub order: u32,
    pub freq_hz: f64,
    pub magnitude: f64,
    pub dbc: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FftAnalysisResult {
    pub spectrum: Vec<FftPoint>,
    pub fundamental_freq: Option<f64>,
    pub fundamental_mag: Option<f64>,
    pub harmonics: Vec<HarmonicInfo>,
    pub thd_percent: Option<f64>,
    pub nyquist_hz: f64,
    pub resolution_hz: f64,
}

/// Computes comprehensive time-domain physical measurements on a sample sequence.
pub fn measure_waveform(samples: &[f64], sample_rate_hz: f64) -> WaveformMeasurements {
    if samples.is_empty() {
        return WaveformMeasurements {
            max: 0.0,
            min: 0.0,
            vpp: 0.0,
            mean: 0.0,
            rms: 0.0,
            frequency: None,
            period_sec: None,
            duty_cycle_percent: None,
        };
    }

    let mut max_val = f64::NEG_INFINITY;
    let mut min_val = f64::INFINITY;
    let mut sum = 0.0;
    let mut sum_sq = 0.0;

    for &s in samples {
        if s > max_val {
            max_val = s;
        }
        if s < min_val {
            min_val = s;
        }
        sum += s;
        sum_sq += s * s;
    }

    let count = samples.len() as f64;
    let mean_val = sum / count;
    let rms_val = (sum_sq / count).sqrt();
    let vpp = (max_val - min_val).max(0.0);

    // High-precision zero-crossing frequency and period estimation with hysteresis
    let mut frequency = None;
    let mut period_sec = None;
    let mut duty_cycle_percent = None;

    if vpp > 1e-4 && samples.len() >= 4 && sample_rate_hz > 0.0 {
        let mid_level = (max_val + min_val) * 0.5;
        let hysteresis = vpp * 0.05; // 5% noise rejection band
        let high_thresh = mid_level + hysteresis;
        let low_thresh = mid_level - hysteresis;

        let mut crossings: Vec<f64> = Vec::new();
        let mut in_high = samples[0] >= mid_level;
        let mut high_samples_count = 0usize;

        for i in 0..samples.len() {
            if samples[i] >= mid_level {
                high_samples_count += 1;
            }

            if i > 0 {
                let prev = samples[i - 1];
                let curr = samples[i];
                if in_high && curr < low_thresh {
                    // Falling transition across mid_level (interpolated sub-sample position)
                    if (prev - curr).abs() > 1e-9 {
                        let frac = (prev - mid_level) / (prev - curr);
                        crossings.push((i - 1) as f64 + frac);
                    }
                    in_high = false;
                } else if !in_high && curr > high_thresh {
                    // Rising transition across mid_level
                    if (curr - prev).abs() > 1e-9 {
                        let frac = (mid_level - prev) / (curr - prev);
                        crossings.push((i - 1) as f64 + frac);
                    }
                    in_high = true;
                }
            }
        }

        // Need at least 2 full cycles (or 3 half crossings) for reliable period estimation
        if crossings.len() >= 3 {
            let mut cycle_lengths = Vec::new();
            for i in 2..crossings.len() {
                // Every 2 half-crossings form a full period
                cycle_lengths.push(crossings[i] - crossings[i - 2]);
            }
            if !cycle_lengths.is_empty() {
                let avg_cycle_samples = cycle_lengths.iter().sum::<f64>() / cycle_lengths.len() as f64;
                if avg_cycle_samples > 0.5 {
                    let period = avg_cycle_samples / sample_rate_hz;
                    let freq = 1.0 / period;
                    period_sec = Some(period);
                    frequency = Some(freq);
                }
            }
        }

        duty_cycle_percent = Some((high_samples_count as f64 / count) * 100.0);
    }

    WaveformMeasurements {
        max: max_val,
        min: min_val,
        vpp,
        mean: mean_val,
        rms: rms_val,
        frequency,
        period_sec,
        duty_cycle_percent,
    }
}

/// Applies standard window functions to reduce spectral leakage.
pub fn apply_window(data: &mut [f64], window_type: &str) {
    let n = data.len();
    if n <= 1 {
        return;
    }
    let n_f64 = (n - 1) as f64;

    match window_type.to_lowercase().as_str() {
        "hanning" | "hann" => {
            for (i, v) in data.iter_mut().enumerate() {
                let w = 0.5 * (1.0 - (2.0 * PI * i as f64 / n_f64).cos());
                *v *= w;
            }
        }
        "hamming" => {
            for (i, v) in data.iter_mut().enumerate() {
                let w = 0.54 - 0.46 * (2.0 * PI * i as f64 / n_f64).cos();
                *v *= w;
            }
        }
        "blackman_harris" | "blackman" => {
            // 4-term Blackman-Harris window (-92 dB sidelobe suppression)
            const A0: f64 = 0.35875;
            const A1: f64 = 0.48829;
            const A2: f64 = 0.14128;
            const A3: f64 = 0.01168;
            for (i, v) in data.iter_mut().enumerate() {
                let x = 2.0 * PI * i as f64 / n_f64;
                let w = A0 - A1 * x.cos() + A2 * (2.0 * x).cos() - A3 * (3.0 * x).cos();
                *v *= w;
            }
        }
        "flattop" | "flat_top" => {
            // Flat Top window (ISO standard for high accuracy amplitude calibration)
            const A0: f64 = 0.21557895;
            const A1: f64 = 0.41663158;
            const A2: f64 = 0.277263158;
            const A3: f64 = 0.083578947;
            const A4: f64 = 0.006947368;
            for (i, v) in data.iter_mut().enumerate() {
                let x = 2.0 * PI * i as f64 / n_f64;
                let w = A0 - A1 * x.cos() + A2 * (2.0 * x).cos() - A3 * (3.0 * x).cos() + A4 * (4.0 * x).cos();
                *v *= w;
            }
        }
        // "rectangular" or none: no alteration
        _ => {}
    }
}

/// In-place Cooley-Tukey Radix-2 Fast Fourier Transform
/// Expects power-of-2 length arrays of real & imag parts.
pub fn fft_radix2(real: &mut [f64], imag: &mut [f64]) {
    let n = real.len();
    assert_eq!(n, imag.len());
    assert!(n.is_power_of_two());

    // Bit-reversal permutation
    let mut j = 0;
    for i in 0..n {
        if i < j {
            real.swap(i, j);
            imag.swap(i, j);
        }
        let mut m = n >> 1;
        while m >= 1 && j >= m {
            j -= m;
            m >>= 1;
        }
        j += m;
    }

    // Butterfly computations
    let mut len = 2;
    while len <= n {
        let half = len >> 1;
        let angle = -2.0 * PI / len as f64;
        let w_step_re = angle.cos();
        let w_step_im = angle.sin();

        for i in (0..n).step_by(len) {
            let mut w_re = 1.0;
            let mut w_im = 0.0;

            for k in 0..half {
                let idx1 = i + k;
                let idx2 = i + k + half;

                let u_re = real[idx1];
                let u_im = imag[idx1];

                let t_re = w_re * real[idx2] - w_im * imag[idx2];
                let t_im = w_re * imag[idx2] + w_im * real[idx2];

                real[idx1] = u_re + t_re;
                imag[idx1] = u_im + t_im;
                real[idx2] = u_re - t_re;
                imag[idx2] = u_im - t_im;

                let next_w_re = w_re * w_step_re - w_im * w_step_im;
                let next_w_im = w_re * w_step_im + w_im * w_step_re;
                w_re = next_w_re;
                w_im = next_w_im;
            }
        }
        len <<= 1;
    }
}

/// Computes FFT spectrum and harmonic distortion from raw input samples.
pub fn compute_fft_spectrum(
    raw_samples: &[f64],
    sample_rate_hz: f64,
    fft_size: usize,
    window_type: &str,
) -> FftAnalysisResult {
    let n = fft_size.next_power_of_two().max(64).min(4096);
    let mut real = vec![0.0; n];
    let mut imag = vec![0.0; n];

    // Copy latest samples (or zero-pad)
    let copy_len = raw_samples.len().min(n);
    let start_idx = raw_samples.len().saturating_sub(copy_len);
    real[..copy_len].copy_from_slice(&raw_samples[start_idx..]);

    // Detrend: remove DC offset before windowing to prevent DC smearing into low frequencies
    let mean_dc = real[..copy_len].iter().sum::<f64>() / copy_len.max(1) as f64;
    for v in real.iter_mut().take(copy_len) {
        *v -= mean_dc;
    }

    // Apply window function
    apply_window(&mut real[..copy_len], window_type);

    // Run Radix-2 FFT
    fft_radix2(&mut real, &mut imag);

    // Compute single-sided amplitude spectrum (0 .. Nyquist)
    let half_n = n / 2;
    let nyquist = sample_rate_hz * 0.5;
    let freq_bin_hz = sample_rate_hz / n as f64;

    let mut spectrum = Vec::with_capacity(half_n);
    // Normalization factor: 2 / N for single-sided (DC bin is 1 / N)
    let norm = 2.0 / copy_len.max(1) as f64;

    let mut max_mag = 0.0;
    let mut fund_bin = 0;

    for i in 1..half_n {
        let mag = (real[i] * real[i] + imag[i] * imag[i]).sqrt() * norm;
        let db = if mag > 1e-12 {
            20.0 * (mag / 1.0).log10()
        } else {
            -120.0
        };

        if mag > max_mag {
            max_mag = mag;
            fund_bin = i;
        }

        spectrum.push(FftPoint {
            freq_hz: i as f64 * freq_bin_hz,
            magnitude: mag,
            db,
        });
    }

    // Harmonic & THD calculation
    let mut fundamental_freq = None;
    let mut fundamental_mag = None;
    let mut harmonics = Vec::new();
    let mut thd_percent = None;

    if max_mag > 1e-4 && fund_bin > 0 {
        let f0 = fund_bin as f64 * freq_bin_hz;
        fundamental_freq = Some(f0);
        fundamental_mag = Some(max_mag);

        harmonics.push(HarmonicInfo {
            order: 1,
            freq_hz: f0,
            magnitude: max_mag,
            dbc: 0.0,
        });

        let mut sum_harmonics_sq = 0.0;

        // Search up to 10th harmonic
        for order in 2..=10 {
            let target_bin = fund_bin * order;
            if target_bin >= half_n {
                break;
            }
            // Search ±1 bin around expected harmonic to handle slight frequency variation
            let mut harm_mag = 0.0;
            let mut actual_bin = target_bin;
            let min_b = target_bin.saturating_sub(1);
            let max_b = (target_bin + 1).min(half_n - 1);
            for b in min_b..=max_b {
                let m = (real[b] * real[b] + imag[b] * imag[b]).sqrt() * norm;
                if m > harm_mag {
                    harm_mag = m;
                    actual_bin = b;
                }
            }

            sum_harmonics_sq += harm_mag * harm_mag;
            let dbc = if harm_mag > 1e-12 && max_mag > 1e-12 {
                20.0 * (harm_mag / max_mag).log10()
            } else {
                -100.0
            };

            harmonics.push(HarmonicInfo {
                order: order as u32,
                freq_hz: actual_bin as f64 * freq_bin_hz,
                magnitude: harm_mag,
                dbc,
            });
        }

        if max_mag > 0.0 {
            let thd = (sum_harmonics_sq.sqrt() / max_mag) * 100.0;
            thd_percent = Some(thd);
        }
    }

    FftAnalysisResult {
        spectrum,
        fundamental_freq,
        fundamental_mag,
        harmonics,
        thd_percent,
        nyquist_hz: nyquist,
        resolution_hz: freq_bin_hz,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_waveform_measurements() {
        // 1000 Hz sine wave sampled at 100 kHz (100 samples per cycle)
        let sample_rate = 100000.0;
        let mut samples = Vec::new();
        for i in 0..500 {
            let t = i as f64 / sample_rate;
            let s = 10.0 * (2.0 * PI * 1000.0 * t).sin();
            samples.push(s);
        }

        let m = measure_waveform(&samples, sample_rate);
        assert!((m.vpp - 20.0).abs() < 0.5);
        assert!((m.max - 10.0).abs() < 0.5);
        assert!((m.min - -10.0).abs() < 0.5);
        assert!(m.mean.abs() < 0.5);
        // RMS of sine wave with amplitude 10 is 10 / sqrt(2) ≈ 7.071
        assert!((m.rms - 7.071).abs() < 0.5);
        assert!(m.frequency.is_some());
        let freq = m.frequency.unwrap();
        assert!((freq - 1000.0).abs() < 20.0);
    }

    #[test]
    fn test_fft_fundamental_detection() {
        let sample_rate = 10000.0;
        let mut samples = Vec::new();
        for i in 0..1024 {
            let t = i as f64 / sample_rate;
            // 500 Hz main sine + 1000 Hz 2nd harmonic
            let s = 5.0 * (2.0 * PI * 500.0 * t).sin() + 1.0 * (2.0 * PI * 1000.0 * t).sin();
            samples.push(s);
        }

        let res = compute_fft_spectrum(&samples, sample_rate, 1024, "hanning");
        assert!(res.fundamental_freq.is_some());
        let f0 = res.fundamental_freq.unwrap();
        assert!((f0 - 500.0).abs() < 20.0);
        assert!(res.thd_percent.is_some());
    }
}
