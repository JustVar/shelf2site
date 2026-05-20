"""One-time script: recalculate data_completeness for all inventory model instances."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import (
    EdgeBox, NUC, Camera, AccessControl, GPU, HardDrive, RamModule,
    CPU, PSU, Motherboard, PCCooling, PCAccessory, Computer, Monitor,
    Phone, MobileDevice, NetworkEquipment, Webcam, Printer,
    OfficeEquipment, UPS, NASDevice, PartNumber, compute_completeness
)

MODELS = [
    EdgeBox, NUC, Camera, AccessControl, GPU, HardDrive, RamModule,
    CPU, PSU, Motherboard, PCCooling, PCAccessory, Computer, Monitor,
    Phone, MobileDevice, NetworkEquipment, Webcam, Printer,
    OfficeEquipment, UPS, NASDevice, PartNumber
]

db = SessionLocal()
total = 0
for Model in MODELS:
    records = db.query(Model).all()
    for record in records:
        record.data_completeness = compute_completeness(record)
        total += 1
    db.commit()
    print(f"{Model.__tablename__}: {len(records)} records updated")

print("Done. " + str(total) + " total records recalculated.")
db.close()
