import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

class TimetableTracker:
    def __init__(self, snapshot_dir="data/timetable_snapshots"):
        self.snapshot_dir = snapshot_dir
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def _classify_semester(self, class_name, class_short):
        """Distinguishes between B.Tech and M.Tech semesters accurately."""
        name_u = str(class_name).upper()
        short_u = str(class_short).upper()

        if "M.TECH" in name_u or "PG" in short_u:
            if "III" in name_u or "3PG" in short_u or "3" in short_u:
                return "M.Tech 3rd Sem"
            elif "I" in name_u or "1PG" in short_u or "1" in short_u:
                return "M.Tech 1st Sem"
            return "M.Tech (PG)"

        if "B.TECH" in name_u or any(short_u.startswith(x) for x in ["1", "3", "5", "7"]):
            if "VII" in name_u or short_u.startswith("7"):
                return "B.Tech 7th Sem"
            elif "V" in name_u or short_u.startswith("5"):
                return "B.Tech 5th Sem"
            elif "III" in name_u or short_u.startswith("3"):
                return "B.Tech 3rd Sem"
            elif "I" in name_u or short_u.startswith("1"):
                return "B.Tech 1st Sem"

        return "Other / First Year"

    def parse_asc_xml(self, xml_source):
        """Parses full card details and lesson associations from aSc Timetable XML."""
        if isinstance(xml_source, str):
            tree = ET.parse(xml_source)
            root = tree.getroot()
        else:
            if hasattr(xml_source, 'read'):
                content = xml_source.read()
            else:
                content = xml_source
            root = ET.fromstring(content)

        # 1. Periods & Timings
        period_map = {}
        for p in root.findall('.//periods/period'):
            p_no = p.attrib.get('period', p.attrib.get('name', ''))
            s_time = p.attrib.get('starttime', '')
            e_time = p.attrib.get('endtime', '')
            timing = f"Period {p_no} ({s_time} - {e_time})" if s_time and e_time else f"Period {p_no}"
            period_map[p_no] = timing

        # 2. Days
        day_map = {
            "100000": "Monday",
            "010000": "Tuesday",
            "001000": "Wednesday",
            "000100": "Thursday",
            "000010": "Friday",
            "000001": "Saturday",
            "1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday"
        }
        for d in root.findall('.//daysdefs/daysdef'):
            d_id = d.attrib.get('id', '')
            d_name = d.attrib.get('name', d.attrib.get('short', ''))
            if d_id and d_name:
                day_map[d_id] = d_name

        # 3. Lookup Entities
        teachers = {t.attrib.get('id', ''): t.attrib.get('name', t.attrib.get('short', '')) for t in root.findall('.//teachers/teacher')}
        subjects = {s.attrib.get('id', ''): f"{s.attrib.get('name', '')} [{s.attrib.get('short', '')}]" if s.attrib.get('short') else s.attrib.get('name', '') for s in root.findall('.//subjects/subject')}
        classes = {c.attrib.get('id', ''): {'name': c.attrib.get('name', ''), 'short': c.attrib.get('short', '')} for c in root.findall('.//classes/class')}
        classrooms = {r.attrib.get('id', ''): r.attrib.get('name', r.attrib.get('short', '')) for r in root.findall('.//classrooms/classroom')}
        groups = {g.attrib.get('id', ''): g.attrib.get('name', '') for g in root.findall('.//groups/group')}

        # 4. Extract Lessons
        lessons = {}
        for l in root.findall('.//lessons/lesson'):
            lid = l.attrib.get('id', '')
            subj_id = l.attrib.get('subjectid', '')
            tch_ids = [tid for tid in l.attrib.get('teacherids', '').split(',') if tid]
            cls_ids = [cid for cid in l.attrib.get('classids', '').split(',') if cid]
            grp_ids = [gid for gid in l.attrib.get('groupids', '').split(',') if gid]
            room_ids = [rid for rid in l.attrib.get('classroomids', '').split(',') if rid]
            periods_count = l.attrib.get('periodspercard', '1')

            cls_names = [classes.get(cid, {}).get('name', cid) for cid in cls_ids]
            cls_shorts = [classes.get(cid, {}).get('short', cid) for cid in cls_ids]

            first_cls_name = cls_names[0] if cls_names else ""
            first_cls_short = cls_shorts[0] if cls_shorts else ""
            sem_program = self._classify_semester(first_cls_name, first_cls_short)

            lessons[lid] = {
                'semester_program': sem_program,
                'subject': subjects.get(subj_id, subj_id),
                'teachers': ", ".join([teachers.get(tid, tid) for tid in tch_ids]) if tch_ids else "No Teacher",
                'classes': ", ".join(cls_names) if cls_names else "All",
                'class_shorts': ", ".join(cls_shorts),
                'groups': ", ".join([groups.get(gid, gid) for gid in grp_ids]) if grp_ids else "Entire Class",
                'classrooms': ", ".join([classrooms.get(rid, rid) for rid in room_ids]) if room_ids else "Unassigned",
                'duration': f"{periods_count} Period(s)"
            }

        # 5. Extract Scheduled Cards (Time Slots)
        slots = []
        for c in root.findall('.//cards/card'):
            lid = c.attrib.get('lessonid', '')
            lesson_info = lessons.get(lid, {})

            raw_day = c.attrib.get('day', c.attrib.get('days', ''))
            day_name = day_map.get(raw_day, f"Day {raw_day}")

            raw_period = c.attrib.get('period', '')
            period_str = period_map.get(raw_period, f"Period {raw_period}")

            card_room_id = c.attrib.get('classroomids', '')
            card_rooms = [classrooms.get(r, r) for r in card_room_id.split(',') if r]
            final_room = ", ".join(card_rooms) if card_rooms else lesson_info.get('classrooms', 'Unassigned')

            # Stable unique key representing a distinct lecture slot
            slot_id = f"{lesson_info.get('classes', '')}___{lesson_info.get('groups', '')}___{lesson_info.get('subject', '')}___{day_name}___{period_str}"

            slots.append({
                'slot_id': slot_id,
                'semester_program': lesson_info.get('semester_program', 'Other'),
                'class': lesson_info.get('classes', ''),
                'class_short': lesson_info.get('class_shorts', ''),
                'group': lesson_info.get('groups', 'Entire Class'),
                'subject': lesson_info.get('subject', ''),
                'teacher': lesson_info.get('teachers', 'No Teacher'),
                'classroom': final_room,
                'day': day_name,
                'period': period_str,
                'duration': lesson_info.get('duration', '1 Period')
            })

        return pd.DataFrame(slots)

    def list_snapshots(self):
        """Returns only saved baseline timetable snapshots."""
        files = [
            f for f in os.listdir(self.snapshot_dir) 
            if f.endswith('.json') and not f.startswith("current_working_copy")
        ]
        return sorted(files, reverse=True)

    def save_snapshot(self, df_records, label=""):
        if not label:
            label = datetime.now().strftime("%d-%m-%Y_%I-%M-%S_%p")
        
        clean_label = label.replace(".json", "")
        filename = f"{clean_label}.json"
        
        filepath = os.path.join(self.snapshot_dir, filename)
        df_records.to_json(filepath, orient="records", indent=2)
        return filepath

    
    def save_current_working_copy(self, df_records):
        filepath = os.path.join(self.snapshot_dir, "current_working_copy.json")
        df_records.to_json(filepath, orient="records", indent=2)
        return filepath

    def _ensure_schema(self, df):
        """Ensures backward compatibility for snapshots saved in earlier versions."""
        if df is not None and not df.empty:
            if 'semester_program' not in df.columns:
                df['semester_program'] = df.apply(
                    lambda r: self._classify_semester(r.get('class', ''), r.get('class_short', '')), 
                    axis=1
                )
            if 'duration' not in df.columns:
                df['duration'] = "1 Period"
        return df

    def load_snapshot(self, filename_or_path):
        if not os.path.isabs(filename_or_path) and not filename_or_path.startswith("data/"):
            filename_or_path = os.path.join(self.snapshot_dir, filename_or_path)
        df = pd.read_json(filename_or_path)
        return self._ensure_schema(df)

    def load_current_working_copy(self):
        filepath = os.path.join(self.snapshot_dir, "current_working_copy.json")
        if os.path.exists(filepath):
            try:
                df = pd.read_json(filepath)
                return self._ensure_schema(df)
            except Exception:
                return None
        return None
    
    def compare_snapshots(self, df_old, df_new):
        """Compares two timetable snapshots and returns rich full card details."""
        old_indexed = df_old.set_index('slot_id')
        new_indexed = df_new.set_index('slot_id')

        old_ids = set(old_indexed.index)
        new_ids = set(new_indexed.index)

        added_ids = new_ids - old_ids
        removed_ids = old_ids - new_ids
        common_ids = old_ids & new_ids

        added_df = new_indexed.loc[list(added_ids)].reset_index() if added_ids else pd.DataFrame()
        removed_df = old_indexed.loc[list(removed_ids)].reset_index() if removed_ids else pd.DataFrame()

        modifications = []
        for sid in common_ids:
            row_old = old_indexed.loc[sid]
            row_new = new_indexed.loc[sid]
            if isinstance(row_old, pd.DataFrame):
                row_old = row_old.iloc[0]
            if isinstance(row_new, pd.DataFrame):
                row_new = row_new.iloc[0]

            changes = []
            for field in ['teacher', 'classroom', 'day', 'period', 'duration']:
                v_old = str(row_old.get(field, '')).strip()
                v_new = str(row_new.get(field, '')).strip()
                if v_old != v_new:
                    changes.append(f"{field.title()}: '{v_old}' → '{v_new}'")

            if changes:
                modifications.append({
                    'semester_program': row_new.get('semester_program', ''),
                    'class': row_new.get('class', ''),
                    'group': row_new.get('group', ''),
                    'subject': row_new.get('subject', ''),
                    'old_teacher': row_old.get('teacher', ''),
                    'new_teacher': row_new.get('teacher', ''),
                    'old_room': row_old.get('classroom', ''),
                    'new_room': row_new.get('classroom', ''),
                    'old_timing': f"{row_old.get('day', '')} {row_old.get('period', '')}",
                    'new_timing': f"{row_new.get('day', '')} {row_new.get('period', '')}",
                    'changes_summary': ", ".join(changes)
                })

        return added_df, removed_df, pd.DataFrame(modifications)