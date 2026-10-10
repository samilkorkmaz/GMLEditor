<?xml version="1.0" encoding="UTF-8"?>
<!--
  Sample GML for Ankara, Turkey.
  CRS: EPSG:4326 (WGS84). Coordinates are written as "longitude latitude" (x y).
  Geometries are approximate and for testing only; they are not survey data.
  Buildings are 3D polygons (x,y,z): z is the roof height in metres above ground
  level (equal to the height_m attribute). Roads are 2D. When DTED is loaded,
  add the terrain elevation at each vertex to z.
-->
<ogr:FeatureCollection
    xmlns:ogr="http://ogr.maptools.org/"
    xmlns:gml="http://www.opengis.net/gml"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

  <gml:boundedBy>
    <gml:Box>
      <gml:coord><gml:X>32.76</gml:X><gml:Y>39.87</gml:Y></gml:coord>
      <gml:coord><gml:X>32.875</gml:X><gml:Y>39.943</gml:Y></gml:coord>
    </gml:Box>
  </gml:boundedBy>

  <gml:featureMember>
    <ogr:roads fid="roads.0">
      <ogr:name>Ataturk Boulevard</ogr:name>
      <ogr:category>primary</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8541,39.9208 32.8545,39.9260 32.8548,39.9320 32.8543,39.9380 32.8540,39.9415</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.1">
      <ogr:name>Eskisehir Road</ogr:name>
      <ogr:category>highway</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8541,39.9208 32.8300,39.9170 32.8000,39.9100 32.7600,39.9000</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.2">
      <ogr:name>Konya Road</ogr:name>
      <ogr:category>highway</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8541,39.9208 32.8520,39.9050 32.8480,39.8900 32.8400,39.8700</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.3">
      <ogr:name>Anitkabir Access Road</ogr:name>
      <ogr:category>secondary</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8370,39.9255 32.8420,39.9250 32.8480,39.9240 32.8541,39.9225</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.4">
      <ogr:name>Ulus to Castle Road</ogr:name>
      <ogr:category>secondary</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8644,39.9416 32.8600,39.9420 32.8540,39.9415</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.5">
      <ogr:name>Cankaya Road</ogr:name>
      <ogr:category>secondary</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8541,39.9208 32.8650,39.9150 32.8750,39.9060</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.6">
      <ogr:name>North West Connector</ogr:name>
      <ogr:category>tertiary</ogr:category>
      <ogr:geometryProperty>
        <gml:LineString srsName="EPSG:4326">
          <gml:coordinates>32.8540,39.9415 32.8400,39.9420 32.8300,39.9380 32.8200,39.9320 32.8100,39.9250</gml:coordinates>
        </gml:LineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:roads fid="roads.7">
      <ogr:name>Genclik Park Paths</ogr:name>
      <ogr:category>path</ogr:category>
      <ogr:geometryProperty>
        <gml:MultiLineString srsName="EPSG:4326">
          <gml:lineStringMember>
            <gml:LineString>
              <gml:coordinates>32.8480,39.9370 32.8510,39.9385</gml:coordinates>
            </gml:LineString>
          </gml:lineStringMember>
          <gml:lineStringMember>
            <gml:LineString>
              <gml:coordinates>32.8515,39.9380 32.8530,39.9360</gml:coordinates>
            </gml:LineString>
          </gml:lineStringMember>
        </gml:MultiLineString>
      </ogr:geometryProperty>
    </ogr:roads>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:buildings fid="buildings.0">
      <ogr:name>Anitkabir (approx. footprint)</ogr:name>
      <ogr:category>monument</ogr:category>
      <ogr:height_m>40</ogr:height_m>
      <ogr:geometryProperty>
        <gml:Polygon srsName="EPSG:4326" srsDimension="3">
          <gml:outerBoundaryIs>
            <gml:LinearRing>
              <gml:coordinates>32.8350,39.9248,40 32.8366,39.9248,40 32.8366,39.9258,40 32.8350,39.9258,40 32.8350,39.9248,40</gml:coordinates>
            </gml:LinearRing>
          </gml:outerBoundaryIs>
        </gml:Polygon>
      </ogr:geometryProperty>
    </ogr:buildings>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:buildings fid="buildings.1">
      <ogr:name>Ankara Castle (approx. footprint)</ogr:name>
      <ogr:category>historic</ogr:category>
      <ogr:height_m>20</ogr:height_m>
      <ogr:geometryProperty>
        <gml:Polygon srsName="EPSG:4326" srsDimension="3">
          <gml:outerBoundaryIs>
            <gml:LinearRing>
              <gml:coordinates>32.8650,39.9410,20 32.8664,39.9410,20 32.8664,39.9422,20 32.8650,39.9422,20 32.8650,39.9410,20</gml:coordinates>
            </gml:LinearRing>
          </gml:outerBoundaryIs>
        </gml:Polygon>
      </ogr:geometryProperty>
    </ogr:buildings>
  </gml:featureMember>

  <gml:featureMember>
    <ogr:buildings fid="buildings.2">
      <ogr:name>Grand National Assembly (approx. footprint)</ogr:name>
      <ogr:category>government</ogr:category>
      <ogr:height_m>25</ogr:height_m>
      <ogr:geometryProperty>
        <gml:Polygon srsName="EPSG:4326" srsDimension="3">
          <gml:outerBoundaryIs>
            <gml:LinearRing>
              <gml:coordinates>32.8225,39.9105,25 32.8240,39.9105,25 32.8240,39.9115,25 32.8225,39.9115,25 32.8225,39.9105,25</gml:coordinates>
            </gml:LinearRing>
          </gml:outerBoundaryIs>
        </gml:Polygon>
      </ogr:geometryProperty>
    </ogr:buildings>
  </gml:featureMember>

</ogr:FeatureCollection>
