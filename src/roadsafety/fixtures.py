"""Small synthetic teaching records; these are never publisher observations."""
from datetime import date, timedelta

FIXTURE_AS_OF = date(2026, 11, 1)
EXPECTED = {"collisions": 6, "injured": 3, "killed": 1, "involved_vehicles": 6,
            "unknown_borough": 1, "missing_location": 2}


def fixture_records(as_of: date = FIXTURE_AS_OF) -> dict:
    locations = [("BROOKLYN", 40.68, -73.95, 2, 0, 3),
                 (None, None, None, 1, 0, 2),
                 ("QUEENS", 40.73, -73.81, 0, 0, 1),
                 ("MANHATTAN", 0, 0, 0, 1, 0),
                 ("BRONX", 40.85, -73.88, 0, 0, 1),
                 ("STATEN ISLAND", 40.58, -74.15, 0, 0, 2)]
    crashes = []
    for i, (borough, lat, lon, injured, killed, days) in enumerate(locations, 1):
        crashes.append({"collision_id": f"00{i}", "crash_date": str(as_of - timedelta(days=days)),
                        "borough": borough, "latitude": lat, "longitude": lon,
                        "number_of_persons_injured": str(injured),
                        "number_of_persons_killed": str(killed)})
    vehicles = []
    for i, (parent, kind) in enumerate([(1,"Sedan"),(1,"Bicycle"),(2,None),
                                       (3,"Sedan"),(4,"Truck"),(5,"Sedan")], 1):
        vehicles.append({"unique_id": f"0V{i}", "collision_id": f"00{parent}",
                         "crash_date": crashes[parent - 1]["crash_date"], "vehicle_type": kind})
    return {"crashes": crashes, "vehicles": vehicles,
            "provenance": {"source_mode": "fixture", "data_origin": "synthetic",
                           "description": "Invented teaching records; not NYC data", "complete": True}}
