use base64::{engine::general_purpose::STANDARD, Engine};
use minisign_verify::{PublicKey, Signature};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs, path::Path};

#[test]
#[ignore = "requires freshly signed release artifacts from package_release.py"]
fn signed_release_matches_embedded_key_and_rejects_tampering() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let config: Value =
        serde_json::from_slice(&fs::read(root.join("src-tauri/tauri.conf.json")).unwrap()).unwrap();
    let latest: Value =
        serde_json::from_slice(&fs::read(root.join("release/latest.json")).unwrap()).unwrap();
    assert_eq!(latest["version"], config["version"]);

    let platform = &latest["platforms"]["windows-x86_64"];
    let url = platform["url"].as_str().unwrap();
    let prefix = "https://github.com/ZenghuiJIA/ingchips_debug_tools/releases/download/";
    assert!(url.starts_with(prefix), "unexpected url: {url}");
    assert!(
        url.ends_with("/AI-HIL-Debugger-setup.exe"),
        "unexpected asset url: {url}"
    );
    let tag = &url[prefix.len()..url.len() - "/AI-HIL-Debugger-setup.exe".len()];
    assert_eq!(
        tag.trim_start_matches('v'),
        config["version"].as_str().unwrap()
    );

    let key = String::from_utf8(
        STANDARD
            .decode(config["plugins"]["updater"]["pubkey"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap();
    let public = PublicKey::decode(&key).unwrap();
    let encoded = platform["signature"].as_str().unwrap();
    assert_eq!(
        encoded,
        fs::read_to_string(root.join("release/AI-HIL-Debugger-setup.exe.sig"))
            .unwrap()
            .trim()
    );
    let signature =
        Signature::decode(&String::from_utf8(STANDARD.decode(encoded).unwrap()).unwrap()).unwrap();
    let mut installer = fs::read(root.join("release/AI-HIL-Debugger-setup.exe")).unwrap();
    public.verify(&installer, &signature, true).unwrap();
    installer[100] ^= 1;
    assert!(public.verify(&installer, &signature, true).is_err());

    let manifest: Value =
        serde_json::from_slice(&fs::read(root.join("release/release-manifest.json")).unwrap())
            .unwrap();
    for file in manifest["files"].as_array().unwrap() {
        let bytes = fs::read(root.join("release").join(file["name"].as_str().unwrap())).unwrap();
        assert_eq!(bytes.len() as u64, file["bytes"].as_u64().unwrap());
        assert_eq!(format!("{:x}", Sha256::digest(&bytes)), file["sha256"]);
    }
}
