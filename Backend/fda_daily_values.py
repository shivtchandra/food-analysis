# backend/fda_daily_values.py
# FDA Daily Values (DV) reference - numeric DVs used for percent calculations.
# Units are noted in key names (g = grams, mg = milligrams, mcg = micrograms)

FDA_DV = {
    "total_fat_g": 78,            # grams
    "saturated_fat_g": 20,        # grams
    "cholesterol_mg": 300,        # mg
    "sodium_mg": 2300,            # mg
    "total_carbohydrate_g": 275,  # grams
    "dietary_fiber_g": 28,        # grams
    "added_sugars_g": 50,         # grams
    "protein_g": 50,              # grams
    "vitamin_D_mcg": 20,          # micrograms
    "calcium_mg": 1300,           # mg
    "iron_mg": 18,                # mg
    "potassium_mg": 4700,         # mg
    "vitamin_A_mcg_RAE": 900,     # mcg RAE
    "vitamin_C_mg": 90,           # mg
    "vitamin_E_mg": 15,           # mg (alpha-tocopherol)
    "vitamin_K_mcg": 120,         # mcg
    "thiamin_mg": 1.2,
    "riboflavin_mg": 1.3,
    "niacin_mg_NE": 16,
    "vitamin_B6_mg": 1.7,
    "folate_mcg_DFE": 400,
    "vitamin_B12_mcg": 2.4,
    "biotin_mcg": 30,
    "pantothenic_acid_mg": 5,
    "magnesium_mg": 420,
    "zinc_mg": 11,
    "selenium_mcg": 55,
    # Add more keys as needed
}
