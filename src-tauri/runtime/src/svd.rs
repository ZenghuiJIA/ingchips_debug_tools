//! Offline SVD metadata. Device/pack resolution remains a backend capability.
use roxmltree::Node;
use serde_json::{json, Value};
fn child<'a, 'i>(node: Node<'a, 'i>, tag: &str) -> Option<Node<'a, 'i>> {
    node.children().find(|n| n.has_tag_name(tag))
}
fn text(node: Node, tag: &str) -> Option<String> {
    child(node, tag)
        .and_then(|n| n.text())
        .map(|s| s.trim().to_string())
}
fn num(s: &str) -> Result<u64, String> {
    let s = s.trim();
    if let Some(h) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        u64::from_str_radix(h, 16).map_err(|e| e.to_string())
    } else {
        s.parse()
            .map_err(|e: std::num::ParseIntError| e.to_string())
    }
}
fn inherited(node: Node, tag: &str, default: &str) -> String {
    let mut current = Some(node);
    while let Some(n) = current {
        if let Some(v) = text(n, tag) {
            return v;
        }
        current = n.parent();
    }
    default.into()
}
fn expanded<'a, 'i>(node: Node<'a, 'i>, tag: &str, depth: usize) -> Result<Option<String>, String> {
    if depth > 16 {
        return Err("SVD derivedFrom cycle/depth limit".into());
    }
    if let Some(value) = text(node, tag) {
        return Ok(Some(value));
    }
    if let Some(base) = node.attribute("derivedFrom") {
        let root = node.document().root_element();
        let name = base.rsplit('.').next().unwrap();
        let parent = node.parent();
        let candidates: Vec<_> = root
            .descendants()
            .filter(|n| {
                n.tag_name() == node.tag_name() && text(*n, "name").as_deref() == Some(name)
            })
            .collect();
        let found = candidates
            .iter()
            .find(|n| n.parent() == parent)
            .copied()
            .or_else(|| {
                if candidates.len() == 1 {
                    Some(candidates[0])
                } else {
                    None
                }
            })
            .ok_or("SVD derivedFrom base is missing/ambiguous")?;
        return expanded(found, tag, depth + 1);
    }
    Ok(None)
}
pub fn parse(xml: &str, peripheral: Option<&str>) -> Result<Value, String> {
    if xml.len() > 32 * 1024 * 1024 {
        return Err("SVD exceeds 32 MiB".into());
    }
    let doc = roxmltree::Document::parse(xml).map_err(|e| e.to_string())?;
    let root = doc.root_element();
    let mut peripherals = vec![];
    let list = child(root, "peripherals").ok_or("SVD peripherals missing")?;
    for p in list.children().filter(|n| n.has_tag_name("peripheral")) {
        let name = text(p, "name").ok_or("Peripheral name missing")?;
        let base = num(&expanded(p, "baseAddress", 0)?.ok_or("baseAddress missing")?)?;
        if peripheral.is_none() {
            peripherals.push(json!({"name":name,"description":text(p,"description").unwrap_or_default(),"base_address":format!("0x{base:08X}"),"raw_address":base,"group_name":text(p,"groupName").unwrap_or_default()}));
            continue;
        }
        if peripheral != Some(name.as_str()) {
            continue;
        }
        let registers = child(p, "registers")
            .or_else(|| {
                p.attribute("derivedFrom")
                    .and_then(|base| {
                        list.children()
                            .find(|n| text(*n, "name").as_deref() == Some(base))
                    })
                    .and_then(|base| child(base, "registers"))
            })
            .ok_or("SVD registers missing")?;
        let mut output = vec![];
        fn walk(
            node: Node,
            base: u64,
            prefix: &str,
            out: &mut Vec<Value>,
            depth: usize,
        ) -> Result<(), String> {
            if depth > 16 {
                return Err("SVD cluster depth exceeded".into());
            }
            for r in node.children().filter(|n| n.is_element()) {
                if !r.has_tag_name("register") && !r.has_tag_name("cluster") {
                    continue;
                }
                let name = text(r, "name").ok_or("Register/cluster name missing")?;
                let offset =
                    num(&expanded(r, "addressOffset", 0)?.ok_or("addressOffset missing")?)?;
                let dimension = text(r, "dim").map(|s| num(&s)).transpose()?.unwrap_or(1);
                if dimension == 0 || dimension > 4096 {
                    return Err("Invalid SVD dimension".into());
                }
                let increment = text(r, "dimIncrement")
                    .map(|s| num(&s))
                    .transpose()?
                    .unwrap_or(0);
                let indices = text(r, "dimIndex")
                    .map(|s| s.split(',').map(str::to_string).collect::<Vec<_>>());
                for index in 0..dimension {
                    let label = indices
                        .as_ref()
                        .and_then(|a| a.get(index as usize))
                        .cloned()
                        .unwrap_or(index.to_string());
                    let name = if dimension > 1 {
                        name.replace("%s", &label)
                    } else {
                        name.clone()
                    };
                    let full = format!("{prefix}{name}");
                    let address = base
                        .checked_add(offset)
                        .and_then(|n| n.checked_add(index * increment))
                        .ok_or("SVD address overflow")?;
                    if address > u32::MAX as u64 {
                        return Err("SVD address exceeds 32 bits".into());
                    }
                    if r.has_tag_name("cluster") {
                        walk(r, address, &format!("{full}."), out, depth + 1)?;
                        continue;
                    }
                    let size = num(
                        &expanded(r, "size", 0)?.unwrap_or_else(|| inherited(r, "size", "32"))
                    )?;
                    if ![8, 16, 32].contains(&size) {
                        return Err("Unsupported SVD register width".into());
                    }
                    let access = expanded(r, "access", 0)?
                        .unwrap_or_else(|| inherited(r, "access", "read-write"));
                    let mut fields = vec![];
                    if let Some(container) = child(r, "fields") {
                        for field in container.children().filter(|n| n.has_tag_name("field")) {
                            let name = text(field, "name").ok_or("Field name missing")?;
                            let (offset, width) = if let Some(range) = text(field, "bitRange") {
                                let parts: Vec<_> =
                                    range.trim_matches(['[', ']']).split(':').collect();
                                if parts.len() != 2 {
                                    return Err("Invalid bitRange".into());
                                }
                                let msb = num(parts[0])?;
                                let lsb = num(parts[1])?;
                                if msb < lsb {
                                    return Err("Invalid bitRange order".into());
                                }
                                (lsb, msb - lsb + 1)
                            } else if let Some(lsb) = text(field, "lsb") {
                                let lsb = num(&lsb)?;
                                let msb = num(&text(field, "msb").ok_or("Missing msb")?)?;
                                if msb < lsb {
                                    return Err("Invalid bit range".into());
                                }
                                (lsb, msb - lsb + 1)
                            } else {
                                (
                                    num(&text(field, "bitOffset").ok_or("Missing bitOffset")?)?,
                                    num(&text(field, "bitWidth").ok_or("Missing bitWidth")?)?,
                                )
                            };
                            if width == 0 || offset + width > size {
                                return Err("SVD field outside register".into());
                            }
                            fields.push(json!({"name":name,"description":text(field,"description").unwrap_or_default(),"bit_offset":offset,"bit_width":width,"access":text(field,"access").unwrap_or(access.clone()),"read_action":text(field,"readAction"),"modified_write":text(field,"modifiedWriteValues")}));
                        }
                    }
                    out.push(json!({"name":full,"description":expanded(r,"description",0)?.unwrap_or_default(),"address":format!("0x{address:08X}"),"raw_address":address,"size":size,"access":access,"read_action":expanded(r,"readAction",0)?,"modified_write":expanded(r,"modifiedWriteValues",0)?,"reset_value":expanded(r,"resetValue",0)?.unwrap_or_else(||"0x0".into()),"fields":fields}));
                    if out.len() > 10000 {
                        return Err("SVD register limit".into());
                    }
                }
            }
            Ok(())
        }
        walk(registers, base, "", &mut output, 0)?;
        output.sort_by_key(|v| v["raw_address"].as_u64().unwrap());
        return Ok(json!(output));
    }
    if peripheral.is_some() {
        Err("Peripheral not found".into())
    } else {
        Ok(json!(peripherals))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inherited_width_array_and_side_effects() {
        let xml="<device><size>16</size><peripherals><peripheral><name>P</name><baseAddress>0x40000000</baseAddress><registers><register><name>R%s</name><dim>2</dim><dimIncrement>2</dimIncrement><addressOffset>4</addressOffset><readAction>clear</readAction><fields><field><name>F</name><bitRange>[7:4]</bitRange></field></fields></register></registers></peripheral></peripherals></device>";
        let rows = parse(xml, Some("P")).unwrap();
        assert_eq!(rows[1]["raw_address"], 0x40000006u64);
        assert_eq!(rows[0]["size"], 16);
        assert_eq!(rows[0]["read_action"], "clear");
        assert_eq!(rows[0]["fields"][0]["bit_width"], 4);
    }
}
